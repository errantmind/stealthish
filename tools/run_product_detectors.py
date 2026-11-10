"""Local detector regressions of the installed product; no runtime changes."""
import argparse
import asyncio
from contextlib import asynccontextmanager, ExitStack
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
import time
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
WHEEL = ROOT / f'.runtime/package-build/stealthish-{VERSION}-py3-none-any.whl'
ENV = ROOT / '.runtime/standalone-env'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_wheel():
    with zipfile.ZipFile(WHEEL) as wheel:
        for path in (ROOT / 'src/stealthish').rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                assert wheel.read('stealthish/' + path.relative_to(ROOT / 'src/stealthish').as_posix()) == path.read_bytes()
        assert not any(name.startswith('stealthish_lab/') for name in wheel.namelist())
    return sha(WHEEL)


def stage_assets(run):
    # Verify before copying. Nothing here executes downloaded detector code.
    from stealthish_lab.additional_fixtures import verify_assets as verify_additional
    from stealthish_lab.rebrowser_fixtures import verify_assets as verify_rebrowser
    verify_additional(ROOT)
    verify_rebrowser(ROOT)
    metadata = json.loads((ROOT / 'evidence/local/detector-acquisition.json').read_text())
    for row in metadata['files']:
        path = (ROOT / row['path']).resolve()
        assert path.is_relative_to(ROOT / '.cache/detectors')
        assert sha(path) == row['sha256']
    staged = run / 'staged'
    shutil.copytree(ROOT / '.cache/detectors', staged / '.cache/detectors')
    shutil.copytree(ROOT / 'fixtures', staged / 'fixtures')
    result = {p.relative_to(staged).as_posix(): sha(p) for p in sorted(staged.rglob('*')) if p.is_file()}
    (run / 'detector-assets.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


class Subject:
    """Product actions use Request. Raw page access below is test observation only."""
    def __init__(self, session, context, product):
        self.session, self.context, self.product = session, context, product
        self.calls = []

    async def request(self, operation, params):
        from stealthish import Request
        response = await self.session.execute(Request(str(len(self.calls) + 1), operation, params))
        self.calls.append({'operation': operation, 'action': params.get('action'), 'code': response.code})
        if response.code != 'OK':
            raise RuntimeError(f'Product operation failed: {operation}: {response.code}')
        return response

    async def new_page(self):
        if not self.product:
            return await self.context.new_page()
        result = await self.request('tabs', {'action': 'new'})
        return self.session.pages[result.data['tabId']]

    def tab(self, page):
        return next(key for key, value in self.session.pages.items() if value is page)

    async def navigate(self, page, url):
        if self.product:
            return await self.request('navigate', {'url': url, 'tabId': self.tab(page)})
        return await page.goto(url, wait_until='domcontentloaded', timeout=60000)

    async def interact(self, page, action, **params):
        if self.product:
            return await self.request('interact', {'tabId': self.tab(page), 'action': action, **params})
        target = page.locator(params['selector']) if 'selector' in params else None
        if action in ('hover', 'click'):
            await getattr(target, action)()
        elif action == 'type':
            await target.type(params['text'], delay=40)
        elif action == 'scroll':
            await page.mouse.wheel(params.get('x', 0), params.get('y', 0))
        else:
            raise ValueError('Unsupported control action')

    async def close_page(self, page):
        if self.product and page in self.session.pages.values():
            await self.request('tabs', {'action': 'close', 'tabId': self.tab(page)})
        elif not page.is_closed():
            await page.close()


@asynccontextmanager
async def subject(config, mode):
    from stealthish import BrowserSession
    if mode == 'product':
        async with BrowserSession(config) as session:
            yield Subject(session, session._context, True)
    else:
        # Same installed environment, genuine Chrome, GPU and blocker. No identity
        # adaptation or human-input patch. Not a supported product configuration.
        from patchright.async_api import async_playwright
        from stealthish.blocker import load_blocker
        from stealthish.compatibility import launch_options
        from stealthish.ownership import ProfileLock
        from stealthish.release import load_release
        from stealthish.localcheck import local_check_server, check_filtering
        with ProfileLock(config.data_dir):
            release = load_release(config)
            async with async_playwright() as runtime:
                context = await runtime.chromium.launch_persistent_context(
                    str(config.data_dir / 'profile'), **launch_options(release))
                try:
                    await load_blocker(context, config, release)
                    with local_check_server() as (origin, token, receipts):
                        await check_filtering(context, origin, token, receipts)
                    yield Subject(None, context, False)
                finally:
                    await context.close()


async def navigate(subject, page, url, gate=None, script=None):
    if gate is None:
        await subject.navigate(page, url)
        return {'order': 'DETECTOR_FIRST', 'status': 'PASS'}
    with gate.arm(script) as state:
        task = asyncio.create_task(subject.navigate(page, url))
        try:
            if not await asyncio.to_thread(state['requested'].wait, 8):
                raise RuntimeError('Local detector script was not requested')
            if subject.product:
                # Test-only helper initialization; the normal product API remains unchanged.
                engine = page._impl_obj._cloak_human
                async with asyncio.timeout(10):
                    value = await engine.worlds.evaluate(page._impl_obj.main_frame, 'true')
                if value is not True:
                    raise RuntimeError('Input helper initialization failed')
            state['record']['inputWorld'] = 'READY' if subject.product else 'NOT_INSTALLED_CONTROL'
            state['record']['initializedAt'] = time.monotonic()
            state['record']['status'] = 'PASS'
            state['release'].set()
            await task
            await page.wait_for_load_state('load', timeout=30000)
            state['record']['loadedAt'] = time.monotonic()
            return dict(state['record'])
        finally:
            state['release'].set()
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass


async def wait_json(page, selector, predicate=None, timeout=45):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if await page.locator(selector).count():
            text = await page.locator(selector).text_content()
            if text:
                value = json.loads(text)
                if value.get('status') == 'ERROR':
                    raise RuntimeError('Detector reported an error: ' + str(value.get('error', value.get('errors'))))
                if predicate is None or predicate(value):
                    return value
        await asyncio.sleep(.15)
    raise TimeoutError('Local detector result did not become ready: ' + selector)


def observe(page):
    result = {'pageErrors': [], 'failedRequests': [], 'requests': []}
    page.on('pageerror', lambda error: result['pageErrors'].append(str(error)))
    page.on('requestfailed', lambda req: result['failedRequests'].append({'url': req.url, 'failure': req.failure}))
    page.on('request', lambda req: result['requests'].append({'url': req.url, 'type': req.resource_type}))
    return result


async def rebrowser(subject, origin, foreign, requests, gate):
    from stealthish_lab.rebrowser_case import assess, csp_controls
    page = await subject.new_page()
    result, actions = observe(page), []
    try:
        start = len(requests)
        result['activation'] = await navigate(subject, page, origin + '/', gate, '/index.js')
        await page.locator('#detections-json').wait_for()
        began = time.monotonic()
        # Upstream's documented probes. These are not product API operations.
        probes = [('dummy-main-world', 'window.dummyFn()', {'isolated_context': False}),
                  ('source-url-default-world', "document.getElementById('detections-json')?.tagName", {}),
                  ('main-world-default', "document.getElementsByClassName('div').length", {})]
        for name, code, options in probes:
            try:
                value = await page.evaluate(code, **options)
                actions.append({'name': name, 'status': 'PASS', 'result': value})
            except Exception as error:
                actions.append({'name': name, 'status': 'ERROR', 'error': str(error)})
        await subject.interact(page, 'hover', selector='#detections-json')
        await subject.interact(page, 'click', selector='#detections-json')
        await asyncio.sleep(max(0, 12 - (time.monotonic() - began)))
        rows = json.loads(await page.locator('#detections-json').input_value())
        observer = json.loads(await page.locator('#lab-observer').text_content())
        sample = list(requests[start:])
        controls = await csp_controls(subject.context, origin, foreign)
        blocked = any(x['blockedURI'] == foreign + '/csp-script.js' and
                      x['directive'] == 'script-src-elem' and x['disposition'] == 'enforce'
                      for x in observer['violations'])
        sent = [r for r in sample if r['origin'] == foreign and r['path'] == '/csp-script.js']
        csp = {'status': 'PASS' if blocked and not sent and controls['status'] == 'PASS' else 'ERROR',
               'enforcementObserved': blocked, 'blockedScriptRequestCount': len(sent), 'positiveControls': controls}
        result.update(raw=rows, observer=observer, actions=actions, csp=csp,
                      assessment=assess(rows, actions, observer, csp, stress=False))
        return result
    finally:
        await subject.close_page(page)


async def earlier(subject, origin, name, gate):
    from stealthish_lab.concealment_case import detector_summary
    page = await subject.new_page()
    result = observe(page)
    try:
        url, script = ('/detectors/botd', '/detectors/botd.js') if name == 'botd' else ('/creep/', '/creep/creep.js')
        result['activation'] = await navigate(subject, page, origin + url, gate, script)
        # Natural order means detector execution starts before the first input helper use.
        value = await wait_json(page, '#result')
        await subject.interact(page, 'hover', selector='body')
        result.update(raw=value, assessment=detector_summary({name: value})[name])
        return result
    finally:
        await subject.close_page(page)


async def additional(subject, origin, name):
    from stealthish_lab.additional_case import TEXT, assess_fpscanner, assess_bot_signal, assess_brotector
    page = await subject.new_page()
    result = observe(page)
    began = time.monotonic()
    try:
        suffix = '?crash=false' if name == 'brotector' else ''
        await subject.navigate(page, origin + '/' + name + '/' + suffix)
        await wait_json(page, '#lab-result', lambda x: x['status'] == ('DONE' if name == 'fpscanner' else 'READY'))
        if name == 'bot-signal':
            if subject.product:
                for selector in ('#field', '#action', '#field'):
                    await subject.interact(page, 'hover', selector=selector)
            else:
                await page.mouse.move(80, 280)
                await page.mouse.move(780, 360, steps=60)
            await subject.interact(page, 'click', selector='#field')
            await subject.interact(page, 'type', selector='#field', text=TEXT)
            for _ in range(10):
                await subject.interact(page, 'scroll', x=0, y=120)
                await asyncio.sleep(.1)
            await subject.interact(page, 'click', selector='#action')
            await subject.interact(page, 'click', selector='#action')
            state = await wait_json(page, '#lab-result', lambda x: x.get('elapsedMs', 0) >= 8500 and
                                    x.get('fieldValue') == TEXT and x.get('actionCount') == 2, timeout=15)
        else:
            if name == 'brotector':
                await subject.interact(page, 'hover', selector='#clickHere')
                await subject.interact(page, 'click', selector='#clickHere')
                await subject.interact(page, 'scroll', x=0, y=100)
                await asyncio.sleep(3)
            state = await wait_json(page, '#lab-result')
        assess = {'fpscanner': assess_fpscanner, 'bot-signal': assess_bot_signal, 'brotector': assess_brotector}[name]
        assessment = assess(state)
        assessment['failedResourceCount'] = len(result['failedRequests'])
        if result['pageErrors']:
            assessment['execution'] = 'ERROR'
        if name == 'bot-signal':
            assessment['notRun'] = ['server IP/TLS/reputation']
            assessment['behavioral']['notRun'] = ['touch', 'manual-human reference']
            assessment['behavioral']['inputMode'] = 'product public API, MIT careful' if subject.product else 'ordinary driver control'
        if name == 'brotector':
            assessment['pdfCoverage'] = 'INCONCLUSIVE' if any('chrome-extension:' in x['url'] or '.pdf' in x['url']
                for x in result['failedRequests']) else 'INITIALIZER_COMPLETED'
        result.update(raw=state, assessment=assessment, elapsedSeconds=time.monotonic() - began)
        return result
    finally:
        await subject.close_page(page)


async def exercise(config, mode, order, staged, report):
    from stealthish_lab.rebrowser_fixtures import rebrowser_servers
    from stealthish_lab.additional_fixtures import additional_server
    from stealthish_lab.fixtures import fixture_servers
    from stealthish_lab.regression_gate import ScriptGate
    from stealthish_lab.containment import process_evidence
    requests = {'rebrowser': [], 'earlier': [], 'additional': []}
    gate = ScriptGate() if order == 'preloaded' else None
    report['detectors'], report['httpRequests'] = {}, requests
    with ExitStack() as stack:
        rb, foreign = stack.enter_context(rebrowser_servers(staged, requests['rebrowser'], script_gate=gate))
        early, _ = stack.enter_context(fixture_servers(staged, observations=requests['earlier'], script_gate=gate))
        extra = stack.enter_context(additional_server(staged, requests['additional']))
        async with subject(config, mode) as client:
            report['processEvidence'] = process_evidence(config.data_dir / 'profile')
            # Include every collection failure. No retry based on a verdict.
            jobs = [('rebrowser', lambda: rebrowser(client, rb, foreign, requests['rebrowser'], gate)),
                    *[(name, lambda name=name: earlier(client, early, name, gate)) for name in ('botd', 'creepjs')],
                    *[(name, lambda name=name: additional(client, extra, name)) for name in ('fpscanner', 'bot-signal', 'brotector')]]
            for name, job in jobs:
                try:
                    report['detectors'][name] = await job()
                except Exception as error:
                    report['detectors'][name] = {'assessment': {'execution': 'ERROR'}, 'error': str(error)}
            report['apiCalls'] = client.calls
            report['scriptGates'] = gate.records if gate else []
            if client.product:
                cdp = await client.context.browser.new_browser_cdp_session()
                report['identityStatus'] = await cdp.send('Stealthish.identityStatus')
                await cdp.detach()
    bad = [name for name, result in report['detectors'].items() if result['assessment'].get('execution') != 'PASS']
    report['collectionErrors'] = bad
    if bad:
        raise RuntimeError('Incomplete detector execution: ' + ', '.join(bad))


def child(run):
    # Load test infrastructure before denying project/production reads.
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tools')]
    from stealthish_lab.containment import preflight
    from stealthish_lab import (  # noqa: F401
        rebrowser_case, additional_case, concealment_case, fixtures, concealment_fixtures,
    )
    from stealthish_lab import additional_fixtures, rebrowser_fixtures, regression_gate  # noqa: F401
    from stealthish_lab.setup import initial_setup
    sys.path.remove(str(ROOT / 'src'))
    sys.path.remove(str(ROOT / 'tools'))
    invocation = json.loads((run / 'invocation.json').read_text())
    report = {'mode': invocation['mode'], 'order': invocation['order'], 'startedAt': datetime.now(timezone.utc).isoformat()}
    try:
        report['containment'] = preflight(invocation['namespaces'], invocation['canary'], ROOT)
        from stealthish import SessionConfig
        import stealthish
        assert Path(stealthish.__file__).is_relative_to(ENV)
        report['package'] = stealthish.__file__
        for name, expected in json.loads((run / 'detector-assets.json').read_text()).items():
            assert sha(run / 'staged' / name) == expected, name
        denied = [ROOT / name for name in ('src', 'tools', '.cache', 'analysis', 'evidence')]
        denied += [Path('/home/errant/dev/max/stealthish-research-archive'), Path('/home/errant/tmp')]

        def audit(event, args):
            if event not in ('open', 'os.listdir', 'os.scandir') or not args or not isinstance(args[0], (str, bytes, os.PathLike)):
                return
            path = Path(os.path.abspath(os.fsdecode(args[0])))
            if any(path == base or path.is_relative_to(base) for base in denied):
                raise PermissionError('Research path access is forbidden during the product test')
        sys.addaudithook(audit)
        config = SessionConfig.load(run / 'data/config.toml')
        asyncio.run(initial_setup(config))
        asyncio.run(exercise(config, invocation['mode'], invocation['order'], run / 'staged', report))
        report['status'] = 'PASS'
    except BaseException as error:
        report['status'] = 'FAIL'
        report['error'] = f'{type(error).__name__}: {error}'
        import traceback
        traceback.print_exc()
    report['finishedAt'] = datetime.now(timezone.utc).isoformat()
    (run / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return 0 if report['status'] == 'PASS' else 1


def outer(mode, order):
    sys.path.insert(0, str(ROOT / 'src'))
    from stealthish_lab.setup import HostCanary
    from stealthish_lab.containment import sandbox_command, namespace
    verify_wheel()
    run = ROOT / '.runtime' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-detectors-' + secrets.token_hex(4))
    run.mkdir(mode=0o700)
    for name in ('home/config', 'home/cache', 'home/run'):
        (run / name).mkdir(parents=True, mode=0o700)
    subprocess.run([str(ROOT / '.venv/bin/python'), '-B', str(ROOT / 'tools/prepare_development_release.py'), str(run / 'data')], check=True)
    stage_assets(run)
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for area in ('src', 'fixtures', 'tools')
              for p in sorted((ROOT / area).rglob('*')) if p.is_file() and '__pycache__' not in p.parts}
    with HostCanary() as canary:
        (run / 'invocation.json').write_text(json.dumps({
            'namespaces': {x: namespace(x) for x in ('net', 'pid', 'mnt', 'user')},
            'canary': canary.port, 'mode': mode, 'order': order, 'wheelSHA256': sha(WHEEL),
            'sourceHashes': hashes, 'packagingHashes': {n: sha(ROOT / n) for n in ('pyproject.toml', 'uv.lock')},
        }, indent=2) + '\n')
        command = sandbox_command(ROOT, run, [])
        command = command[:command.index('--') + 1] + [str(ENV / 'bin/python'), '-I', '-B', str(Path(__file__).resolve()), '--child', str(run)]
        code = 1
        with (run / 'stdout.log').open('w') as out, (run / 'stderr.log').open('w') as err:
            try:
                code = subprocess.run(command, stdout=out, stderr=err, timeout=360,
                    env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8'}).returncode
            except subprocess.TimeoutExpired:
                err.write('Outer test deadline expired. No result is accepted.\n')
        observer = {'status': 'PASS' if not any(canary.received.values()) else 'FAIL', 'receipts': canary.received}
    (run / 'host-observer.json').write_text(json.dumps(observer, indent=2) + '\n')
    print(json.dumps({'run': str(run), 'exit': code, 'observer': observer, 'mode': mode, 'order': order}))
    return code


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', type=Path)
    parser.add_argument('--mode', choices=('product', 'stock-control'), default='product')
    parser.add_argument('--order', choices=('natural', 'preloaded'), default='natural')
    args = parser.parse_args()
    raise SystemExit(child(args.child) if args.child else outer(args.mode, args.order))
