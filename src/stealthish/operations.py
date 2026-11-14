"""Browser operations shared by both interfaces. No raw JavaScript operation."""
import asyncio
import secrets

from .artifacts import requested, save_text
from .errors import StealthishError
from .extraction import readable, raw_html
from . import search, tabs
from .protocol import CAPABILITIES, Request, Result, http_url
from .references import redact_fields
from .verification import inspect


def limit(config, params):
    value = params.get("maxChars", config.text_limit)
    if type(value) is not int or not 1 <= value <= 100000:
        raise StealthishError("INVALID_REQUEST")
    return value


def clipped(result, text, length):
    result.truncation = {"truncated": len(text) > length, "characters": len(text), "limit": length}
    return text[:length]


def save_requested(params, truncated):
    explicit = requested(params, "saveArtifact")
    on_truncation = requested(params, "saveOnTruncation")
    return explicit or (on_truncation and truncated)


def navigation_options(config, params):
    wait = params.get("waitUntil", "domcontentloaded")
    timeout = params.get("timeoutMs", config.navigation_timeout * 1000)
    if wait not in {"commit", "domcontentloaded", "load", "networkidle"} or \
            type(timeout) not in {int, float} or not 1 <= timeout <= 600000:
        raise StealthishError("INVALID_REQUEST")
    return {"wait_until": wait, "timeout": timeout}


async def execute(session, request):
    config, params, op = session.config, request.params, request.operation
    result = Result(request.id)
    if op == "session_status":
        result.data = {"mode": "headless" if config.headless else "headed",
                       "running": bool(session._context and session._context.browser.is_connected()),
                       "release": config.release, "capabilities": CAPABILITIES,
                       "selectedTab": session.selected if config.headless else None,
                       "pausedTabs": session.paused.copy() if config.headless else {},
                       "actionTimeoutMs": config.action_timeout * 1000,
                       "support": "EXPERIMENTAL_LINUX", "blocker": "verified"}
        return result
    if op == "close":
        return result
    if op == "manual_open":
        if config.headless:
            raise StealthishError("INVALID_REQUEST")
        url = http_url(params.get("url"))
        tab, page = session.page({}) if session.pages else await session.new_page()
        # Explicit control navigation only. Do not inspect the destination,
        # classify its fields, take a snapshot, or return its title/URL.
        session.effect = "unknown"
        await page.goto(url, wait_until="domcontentloaded", timeout=config.navigation_timeout * 1000)
        result.data = {"mode": "headed", "running": True}
        result.effect = "applied"
        return result
    if not config.headless:
        raise StealthishError("MANUAL_ACCESS")
    if op == "restart":
        if params.get("acknowledgeStateLoss") is not True:
            raise StealthishError("INVALID_REQUEST")
        await session.restart()
        result.data = {"tabId": session.selected, "release": config.release, "mode": "headless"}
        result.warnings = ["Tabs, references, and tab pause state were discarded. No page was reopened."]
        result.effect = "applied"
        return result
    if op == "search":
        length = limit(config, params)
        engine = params.get("engine", config.search_engine)
        url = search.query_url(params.get("query"), engine)
        target = {key: value for key, value in params.items() if key in {"tabId", "tabPolicy", "timeoutMs"}}
        target["url"] = url
        if "tabId" not in params:
            target.setdefault("tabPolicy", "reuse-domain")
        navigated = await execute(session, Request(request.id, "navigate", target))
        tab, page = session.page({"tabId": navigated.data["tabId"]})
        data, result.truncation, result.warnings, full = await search.collect(page, length, engine)
        if data["kind"] == "fallback":
            info = search.engine_info(engine)
            try:
                await page.locator(info["containers"]).first.wait_for(
                    state="visible", timeout=min(params.get("timeoutMs", 15000), 15000))
            except Exception:
                pass
            await session.check_pause(tab, page, url)
            data, result.truncation, result.warnings, full = await search.collect(page, length, engine)
        while await session.check_pause(tab, page, url):
            # Re-read after an automatic redirect; never resubmit the search.
            data, result.truncation, result.warnings, full = await search.collect(page, length, engine)
        result.data = {**await tabs.context(session, tab), "engine": engine, "url": page.url, **data}
        if requested(params, "saveOnTruncation") and result.truncation["truncated"]:
            result.data["artifact"] = save_text(config, full, "txt")
        result.effect = "applied"
        return result
    if op == "tabs":
        action = params.get("action", "list")
        if action == "list":
            result.data = {"tabs": [await tabs.info(session, key) for key in
                                    sorted(session.pages, key=lambda key: session.access.get(key, 0), reverse=True)
                                    if not session.pages[key].is_closed()]}
        elif action == "new":
            if "url" in params:
                target = {key: value for key, value in params.items() if key in {"url", "waitUntil", "timeoutMs"}}
                target["tabPolicy"] = "new"
                return await execute(session, Request(request.id, "navigate", target))
            await session.new_page()
            result.effect = "applied"
        elif action in {"select", "close"}:
            tab, page = session.page(params)
            if action == "close":
                session.effect = "unknown"
                await page.close()
                if not session.pages:
                    await session.new_page()
            result.effect = "applied"
        else:
            raise StealthishError("INVALID_REQUEST")
        result.data.update(await tabs.context(session))
        return result
    if op == "navigate":
        action = params.get("action", "goto")
        if action not in {"goto", "back", "forward", "reload"}:
            raise StealthishError("INVALID_REQUEST")
        policy = params.get("tabPolicy", "current")
        if policy not in {"auto", "current", "new", "reuse-domain"}:
            raise StealthishError("INVALID_REQUEST")
        url = http_url(params.get("url")) if action == "goto" else None
        if action != "goto" and (policy != "current" or "url" in params):
            raise StealthishError("INVALID_REQUEST")
        options = navigation_options(config, params)
        if url:
            session.check_site_pause(url)
        tab, page = await tabs.choose(session, url, policy, params.get("tabId"))
        await session.check_pause(tab, page)
        session.refs.invalidate(tab)
        session.effect = "unknown"
        if action == "goto":
            await page.goto(url, **options)
        elif action == "reload":
            await page.reload(**options)
        elif action == "back":
            await page.go_back(**{**options, "wait_until": params.get("waitUntil", "commit")})
        else:
            await page.go_forward(**{**options, "wait_until": params.get("waitUntil", "commit")})
        session.selected = tab
        session.effect = "applied"
        await session.check_pause(tab, page, url)
        result.data = {**await tabs.context(session, tab), "url": page.url}
        result.effect = "applied"
        return result

    tab, page = session.page(params)
    if op == "resume":
        if params.get("confirmed") is not True:
            raise StealthishError("INVALID_REQUEST")
        state = await inspect(page)
        if state["signal"]:
            signal = state["signal"]
            raise session.verification.error(tab, page, signal,
                                             "still-present" if signal.automatic else "human-required")
        if not state["ready"]:
            raise StealthishError("CHALLENGE_REQUIRED")
        session.paused.pop(tab, None)
        session.pause_errors.pop(tab, None)
        session.verification.forget(tab)
        site = session.pause_origins.pop(tab, None)
        if site and site not in session.pause_origins.values():
            session.paused_sites.discard(site)
        return result
    await session.check_pause(tab, page)
    if op == "snapshot":
        length = limit(config, params)
        boxes = requested(params, "boxes")
        text = await page.aria_snapshot(mode="ai", boxes=boxes)
        while await session.check_pause(tab, page):
            text = await page.aria_snapshot(mode="ai", boxes=boxes)
        text = session.refs.snapshot(tab, redact_fields(text))
        result.data = {"text": clipped(result, text, length)}
        if save_requested(params, result.truncation["truncated"]):
            result.data["artifact"] = save_text(config, text, "txt")
    elif op == "extract":
        length = limit(config, params)
        html_requested = requested(params, "includeHtml")
        text, method, result.warnings = await readable(page)
        html = await raw_html(page) if html_requested else None
        while await session.check_pause(tab, page):
            text, method, result.warnings = await readable(page)
            html = await raw_html(page) if html_requested else None
        result.data = {"method": method, "text": clipped(result, text, length)}
        if save_requested(params, result.truncation["truncated"]):
            result.data["artifact"] = save_text(config, text, "txt")
        if html_requested:
            result.data["htmlArtifact"] = save_text(config, html, "html")
            result.warnings.append("The explicit raw HTML artifact can contain sensitive page data.")
    elif op == "interact":
        delay = params.get("waitAfterMs", 0)
        if type(delay) not in {int, float} or not 0 <= delay <= 30000:
            raise StealthishError("INVALID_REQUEST")
        raw = session.refs.resolve(tab, params["ref"]) if "ref" in params else None
        before = set(session.pages)
        session.effect = "unknown"
        await session.input.perform(page, params, raw)
        if delay:
            await asyncio.sleep(delay / 1000)
        if session._popup_tasks:
            await asyncio.gather(*list(session._popup_tasks))
        added = [key for key in session.pages if key not in before]
        if added:
            tab, page = session.page({"tabId": added[-1]})
        elif page.is_closed():
            tab, page = session.page({}) if session.pages else await session.new_page()
        await session.check_pause(tab, page)
        result.effect = "applied"
        if params.get("action") in {"scroll", "key"}:
            result.warnings.append("Direct wheel/global key input has limited humanization.")
    elif op == "screenshot":
        full = params.get("fullPage", True)
        if type(full) is not bool:
            raise StealthishError("INVALID_REQUEST")
        path = config.data_dir / "artifacts" / (secrets.token_hex(16) + ".png")
        await page.screenshot(path=str(path), full_page=full)
        path.chmod(0o600)
        result.data = {"path": str(path), "format": "png"}
        result.effect = "applied"
    else:
        raise StealthishError("UNSUPPORTED")
    result.data.update(await tabs.context(session, tab))
    return result
