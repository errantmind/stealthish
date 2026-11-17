"""Visual access to one verification encounter. No page reload or query replay."""
import asyncio
import secrets
from urllib.parse import urlsplit

from .errors import StealthishError
from .artifacts import requested, save_text
from .protocol import Result
from .references import redact_fields
from .verification import inspect

PAUSE_CODES = {"CHALLENGE_REQUIRED", "AUTH_REQUIRED", "CONSENT_REQUIRED", "ACCESS_DENIED"}


class Challenges:
    def __init__(self, config):
        self.config = config
        self.entries = {}

    def start(self, tab, origin, current):
        if tab not in self.entries:
            self.entries[tab] = {
                "id": secrets.token_hex(16), "started": asyncio.get_running_loop().time(),
                "actions": 0, "hosts": {urlsplit(origin).hostname, urlsplit(current).hostname},
            }

    def forget(self, tab):
        self.entries.pop(tab, None)

    def info(self, tab):
        entry = self.entries.get(tab)
        if not entry:
            return None
        remaining = max(0, self.config.verification_timeout -
                        (asyncio.get_running_loop().time() - entry["started"]))
        actions = max(0, self.config.verification_actions - entry["actions"])
        state = "scope" if entry.get("outsideScope") else "active" if remaining and actions else "limit"
        return {"verificationId": entry["id"], "state": state,
                "allowInput": state == "active", "remainingActions": actions,
                "remainingSeconds": round(remaining, 1)}

    async def observe(self, session, tab, page):
        state = await inspect(page)
        if state["signal"] is None and state["ready"]:
            # Observe again before releasing a check during a frame replacement.
            await asyncio.sleep(0.25)
            state = await inspect(page)
        signal = state["signal"]
        session.verification.authentication[tab] = state.get("authentication")
        if signal is not None:
            origin = session.pause_origins.get(tab)
            error = (session.verification.error(tab, page, signal, "human-required", state)
                     if signal.code == "AUTH_REQUIRED" else
                     StealthishError(signal.code, data={"rule": signal.rule}))
            session.pause(tab, signal.code, f"https://{origin}/" if origin else page.url, error)
            entry = self.entries.get(tab)
            if entry and urlsplit(page.url).hostname not in entry["hosts"]:
                entry["outsideScope"] = True
        elif state["ready"] and urlsplit(page.url).scheme in {"http", "https"}:
            session.clear_pause(tab)
        return state

    async def result(self, session, tab, page, request_id, *, snapshot=False, params=None):
        params = params or {}
        previous = self.info(tab)
        state = await self.observe(session, tab, page)
        code = session.paused.get(tab, "OK")
        result = Result(request_id, status="paused" if code != "OK" else "ok", code=code,
                        effect=session.effect)
        if code != "OK":
            result.data.update(session.pause_errors[tab].data)
            result.data["message"] = str(session.pause_errors[tab])
            result.data["challenge"] = self.info(tab)
            if result.data["challenge"] and not result.data["challenge"]["allowInput"]:
                result.data["message"] = str(StealthishError(
                    "VERIFICATION_SCOPE" if result.data["challenge"]["state"] == "scope" else "VERIFICATION_LIMIT"))
            elif result.data["challenge"] and not state["ready"]:
                result.data["challenge"].update(state="loading", allowInput=False, allowWait=True)
        else:
            result.data["challenge"] = ({"state": "cleared", "allowInput": False,
                                         "verificationId": previous["verificationId"]}
                                        if previous else None)
            if tab in session.pending_search:
                from .operations import collect_search
                collected = await collect_search(session, tab, page, request_id,
                                                 session.pending_search[tab], wait=False)
                result.data.update(collected.data)
                result.truncation = collected.truncation
                result.warnings.extend(collected.warnings)
                session.pending_search.pop(tab, None)
        if snapshot:
            text = session.refs.snapshot(tab, redact_fields(await page.aria_snapshot(
                mode="ai", boxes=params.get("boxes", False))))
            maximum = params.get("maxChars", session.config.text_limit)
            if type(maximum) is not int or not 1 <= maximum <= 100000:
                raise StealthishError("INVALID_REQUEST")
            result.data["text"] = text[:maximum]
            result.truncation = {"truncated": len(text) > maximum, "characters": len(text), "limit": maximum}
            if requested(params, "saveArtifact") or (requested(params, "saveOnTruncation") and len(text) > maximum):
                result.data["artifact"] = save_text(session.config, text, "txt")
        image = await session.images.capture(tab, page, session.config.data_dir / "artifacts",
                                             full=params.get("fullPage", False), clip=params.get("clip"))
        result.data.update(image=image, tabId=tab)
        from .tabs import context
        result.data.update(await context(session, tab))
        return result

    async def interact(self, session, tab, page, request):
        params = request.params
        entry = self.entries.get(tab)
        if not entry or params.get("verificationId") != entry["id"]:
            raise StealthishError("VERIFICATION_SCOPE")
        state = await self.observe(session, tab, page)
        if tab not in session.paused:
            # The check cleared before input. Collect the current page without clicking it.
            return await self.result(session, tab, page, request.id)
        if session.paused[tab] != "CHALLENGE_REQUIRED":
            return await self.result(session, tab, page, request.id)
        if not self.info(tab)["allowInput"]:
            return await self.result(session, tab, page, request.id)
        action = params.get("action")
        if action not in {"click", "hover", "scroll", "key", "press", "fill", "type", "wait"}:
            raise StealthishError("INVALID_REQUEST")
        delay = params.get("waitAfterMs", 750)
        if type(delay) not in {int, float} or not 0 <= delay <= 10000:
            raise StealthishError("INVALID_REQUEST")
        if action != "wait" and not state["ready"]:
            return await self.result(session, tab, page, request.id)
        if action != "wait":
            await session.images.validate(tab, page, params.get("imageId"))
            point = None
            if action in {"click", "hover"} and ("x" in params or "y" in params):
                point = await session.images.point(tab, page, params.get("imageId"), params.get("x"), params.get("y"))
            raw = session.refs.resolve(tab, params["ref"]) if "ref" in params else None
            if params.get("key") and params["key"] not in {
                "Tab", "Shift+Tab", "Enter", "Space", "Backspace", "Delete", "Escape",
                "ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End",
            }:
                raise StealthishError("INVALID_REQUEST")
            entry["actions"] += 1
            session.images.invalidate(tab)
            session.refs.invalidate(tab)
            session.effect = "unknown"
            await session.input.perform(page, params, raw, point=point)
            session.effect = "applied"
        if delay:
            await asyncio.sleep(delay / 1000)
        return await self.result(session, tab, page, request.id)
