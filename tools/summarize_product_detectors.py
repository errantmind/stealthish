"""Export all named packaged-runtime detector runs without selecting by score."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('index', type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise SystemExit('Output exists. Keep earlier evidence unchanged.')
    rows = json.loads(args.index.read_text())
    version = tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']['version']
    wheel = ROOT / f'.runtime/package-build/stealthish-{version}-py3-none-any.whl'
    wheel_hash = sha(wheel)
    with zipfile.ZipFile(wheel) as archive:
        for path in (ROOT / 'src/stealthish').rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                assert archive.read('stealthish/' + path.relative_to(ROOT / 'src/stealthish').as_posix()) == path.read_bytes()
    result = {'schemaVersion': 1, 'scope': 'Installed product, local detectors; not release or live-site approval',
        'wheelSHA256': wheel_hash, 'runs': [], 'sourceHashes': None,
        'packagingHashes': {n: sha(ROOT / n) for n in ('pyproject.toml', 'uv.lock')},
        'limits': ['No public endpoint, Cloudflare, account, or native Windows test.',
                   'Rebrowser default isolated-world probes are untriggered; exposed functions are not a product API.',
                   'CreepJS has general headless-like/GPU warnings and unavailable external network results.',
                   'FPScanner does not collect worker webdriver; upstream caught rule exceptions are not explicit errors.',
                   'bot-signal has zero-RTT and direct-scroll flags; touch and manual-human controls are absent.',
                   'Brotector PDF path is inconclusive; crash/Selenium probes are not run.',
                   'Worker first-read/restart risk is not resolved by these tests.',
                   'Controls use the same blocker and GPU with stock Patchright and ordinary input, not the supported product.',
                   'Detector result reads and documented Rebrowser probes use test-only driver access.',
                   'Full Step 5 interfaces and maintenance remain unfinished.']}
    for row in rows:
        run = Path(row['run']).resolve()
        assert run.is_relative_to(ROOT / '.runtime')
        invocation = json.loads((run / 'invocation.json').read_text())
        report = json.loads((run / 'report.json').read_text())
        assert invocation['wheelSHA256'] == wheel_hash
        assert invocation['packagingHashes'] == result['packagingHashes']
        if result['sourceHashes'] is None:
            result['sourceHashes'] = invocation['sourceHashes']
        assert result['sourceHashes'] == invocation['sourceHashes']
        for name, expected in invocation['sourceHashes'].items():
            assert sha(ROOT / name) == expected, name
        assets = json.loads((run / 'detector-assets.json').read_text())
        for name, expected in assets.items():
            assert sha(run / 'staged' / name) == expected, name
        detectors = {}
        for name, data in report.get('detectors', {}).items():
            item = {key: data.get(key) for key in ('assessment', 'error', 'pageErrors', 'failedRequests', 'activation') if key in data}
            if name == 'rebrowser':
                item.update(csp=data.get('csp'), actions=data.get('actions'), observer=data.get('observer'))
            if name == 'bot-signal':
                raw = data.get('raw', {})
                item.update(eventCounts=raw.get('events'), untrustedEvents=raw.get('untrustedEvents'),
                    actionCount=raw.get('actionCount'))
            detectors[name] = item
        result['runs'].append({'runId': run.name, 'index': row['index'], 'mode': report['mode'], 'order': report['order'],
            'execution': report['status'], 'error': report.get('error'), 'containment': report['containment'],
            'observer': json.loads((run / 'host-observer.json').read_text()),
            'processEvidence': report.get('processEvidence'), 'identityStatus': report.get('identityStatus'),
            'apiCalls': report.get('apiCalls'), 'detectors': detectors, 'scriptGates': report.get('scriptGates'),
            'package': report.get('package'), 'startedAt': report['startedAt'], 'finishedAt': report['finishedAt'],
            'releaseManifestSHA256': sha(run / 'data/releases/development/manifest.json'),
            'artifactHashes': {name: sha(run / name) for name in
                ('invocation.json', 'report.json', 'host-observer.json', 'detector-assets.json')}})
    # The staged adapters are byte-for-byte copies; fixture transport rewrites are unchanged lab code.
    result['detectorAssetHashes'] = json.loads((Path(rows[0]['run']) / 'detector-assets.json').read_text())
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print('Saved all', len(rows), 'planned runs:', args.output)


if __name__ == '__main__':
    main()
