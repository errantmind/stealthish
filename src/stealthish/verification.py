"""Passive verification handling. No input, navigation, or extra web requests."""
import asyncio
from collections import deque
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from .errors import StealthishError

WAIT_SECONDS = 10.0
POLL_SECONDS = 0.25
SAFE_ROUTES = {"/", "/search", "/turnstile", "/signin", "/login", "/sorry", "/captcha"}

# Runs in the driver's existing isolated world. Return classifications, not text.
INSPECT = r"""() => {
    const visible=e => !!e && getComputedStyle(e).visibility!=='hidden' && e.getClientRects().length>0;
    const has=s => [...document.querySelectorAll(s)].some(visible);
    const main=document.querySelector('main,#search-results') || document.body;
    const text=main ? main.innerText.slice(0,100000).toLowerCase() : '';
    const ready=!!document.body && ['interactive','complete'].includes(document.readyState);
    const signal=(code,rule,automatic=false)=>({code,rule,automatic});
    let found=null;
    if (has('iframe[src*="recaptcha"][title*="challenge" i]'))
        found=signal('CHALLENGE_REQUIRED','recaptcha-interaction');
    else if (has('#captcha-form, #challenge-form, .g-recaptcha, .anomaly-modal'))
        found=signal('CHALLENGE_REQUIRED','challenge-form');
    else if (has("form[action*='consent']"))
        found=signal('CONSENT_REQUIRED','consent-form');
    else if (has("form input[type='password']"))
        found=signal('AUTH_REQUIRED','password-form');
    else if (has('iframe[src*="challenges.cloudflare.com"], #challenge-running, #challenge-stage, #cf-challenge-running'))
        found=signal('CHALLENGE_REQUIRED','cloudflare-verification',true);
    else if (/^\s*our systems have detected unusual traffic[^\n]*$/m.test(text))
        found=signal('CHALLENGE_REQUIRED','unusual-traffic');
    else if (/^\s*(?:please )?verify you are human to continue[.!]?\s*$/m.test(text))
        found=signal('CHALLENGE_REQUIRED','human-verification-text');
    return {signal:found,ready,documentState:document.readyState};
}"""


def location(url):
    """Keep known route names only. Drop queries, fragments, and variable paths."""
    value = urlsplit(url)
    path = value.path.rstrip("/") or "/"
    if path.startswith("/cdn-cgi/challenge-platform/"):
        path = "/cdn-cgi/challenge-platform/[redacted]"
    elif path not in SAFE_ROUTES:
        path = "/[redacted]"
    return {"host": value.hostname, "route": path}


@dataclass(frozen=True)
class Signal:
    code: str
    rule: str
    automatic: bool = False


async def inspect(page):
    url = page.url
    parsed = urlsplit(url)
    host, route = parsed.hostname or "", parsed.path.rstrip("/")
    route_signal = None
    if host in {"kagi.com", "www.kagi.com"}:
        if route in {"/signin", "/login"}:
            route_signal = Signal("AUTH_REQUIRED", "kagi-sign-in-route")
        elif route == "/turnstile":
            route_signal = Signal("CHALLENGE_REQUIRED", "kagi-turnstile-route", True)
    if host.startswith("consent."):
        route_signal = Signal("CONSENT_REQUIRED", "consent-route")
    elif parsed.path.startswith(("/sorry/", "/captcha")):
        route_signal = Signal("CHALLENGE_REQUIRED", "challenge-route")
    try:
        state = await page.evaluate(INSPECT)
    except Exception as error:
        # An automatic redirect can replace the document while it is observed.
        # This is an incomplete observation, not clearance or another navigation.
        if "Execution context was destroyed" not in str(error) and \
                "Cannot find context" not in str(error):
            raise
        return {"signal": route_signal, "ready": False, "documentState": "transition", "url": url}
    signal = Signal(**state["signal"]) if state["signal"] else None
    if route_signal is not None:
        # A route or Turnstile frame is not proof that human input is required.
        if not route_signal.automatic or signal is None or signal.automatic or \
                signal.rule == "human-verification-text":
            signal = route_signal
    if page.url != url:
        state.update(ready=False, documentState="transition")
    state.update(signal=signal, url=url)
    return state


class Verification:
    def __init__(self):
        self.navigation = {}
        self.attempts = {}
        self.deadline = 0.0
        self.wait_deadline = None

    def begin(self, deadline):
        self.deadline = deadline
        self.wait_deadline = None
        self.navigation.clear()
        self.attempts.clear()

    def forget(self, tab):
        self.navigation.pop(tab, None)
        self.attempts.pop(tab, None)

    def response(self, tab, page, response):
        """Read existing main-document events; never request headers or bodies."""
        try:
            request = response.request
            if not request.is_navigation_request() or request.frame != page.main_frame:
                return
            item = {**location(response.url), "httpStatus": response.status}
            headers = response.headers
            ids = {name: headers[name] for name in ("cf-ray", "x-request-id")
                   if name in headers and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", headers[name])}
            if ids:
                item["requestIds"] = ids
            self.navigation.setdefault(tab, deque(maxlen=12)).append(item)
        except Exception:
            # Missing diagnostics must not change browser behavior.
            return

    def record(self, tab, page, signal, state=None):
        now = asyncio.get_running_loop().time()
        if tab not in self.attempts:
            self.attempts[tab] = {
                "started": now, "rule": signal.rule, "initialRule": signal.rule,
                "code": signal.code, "automatic": signal.automatic, "outcome": "waiting",
            }
        record = self.attempts[tab]
        current = state["signal"] if state is not None else signal
        record.update(final=location(state["url"] if state else page.url),
                      finalRule=current.rule if current else None,
                      code=current.code if current else None,
                      elapsedMs=round((now - record["started"]) * 1000),
                      navigation=list(self.navigation.get(tab, ())))
        if state is not None:
            record.update(documentReady=state["ready"], documentState=state["documentState"])
        return record

    def details(self, tab):
        record = self.attempts.get(tab)
        return {key: value for key, value in record.items() if key != "started"} if record else None

    def error(self, tab, page, signal, outcome, state=None):
        record = self.record(tab, page, signal, state)
        code = signal.code if signal else "TIMEOUT"
        record.update(outcome=outcome, code=code)
        site = "Kagi" if (urlsplit(page.url).hostname or "").removeprefix("www.") == "kagi.com" else "The site"
        message = None
        if code == "TIMEOUT":
            message = "The returned document did not finish loading. No active verification was observed."
        elif code == "CHALLENGE_REQUIRED":
            if outcome == "human-required":
                message = f"{site} requests human verification. The site is paused. No retry was made."
            elif outcome == "interrupted":
                message = f"{site} verification was interrupted. The site remains paused. No retry was made."
            elif outcome == "still-present":
                message = f"{site} verification is still present. The site remains paused. No retry was made."
            else:
                duration = round(record["elapsedMs"] / 1000, 1)
                message = f"{site} verification did not complete within {duration:g} seconds. The site is paused. No retry was made."
        return StealthishError(code, message=message, data={"verification": self.details(tab)})

    @staticmethod
    def ready(state):
        # Search layout is not evidence of a challenge. Parsing happens later.
        return state["ready"] and state["signal"] is None and \
            urlsplit(state["url"]).scheme in {"http", "https"}

    async def check(self, tab, page):
        state = await inspect(page)
        signal = state["signal"]
        if signal is None:
            return False
        if not signal.automatic:
            raise self.error(tab, page, signal, "human-required", state)
        loop = asyncio.get_running_loop()
        if self.wait_deadline is None:
            # Leave a small margin for returning the pause before the action timer.
            self.wait_deadline = min(loop.time() + WAIT_SECONDS, self.deadline - 0.1)
        self.record(tab, page, signal, state)
        try:
            async with asyncio.timeout_at(self.wait_deadline):
                while True:
                    await asyncio.sleep(POLL_SECONDS)
                    state = await inspect(page)
                    current = state["signal"]
                    if current is not None and not current.automatic:
                        raise self.error(tab, page, current, "human-required", state)
                    self.record(tab, page, signal, state)
                    if self.ready(state):
                        self.attempts[tab]["outcome"] = "cleared"
                        return True
        except TimeoutError:
            current = state["signal"]
            raise self.error(tab, page, current, "deadline" if current else "document-timeout", state) from None
        except asyncio.CancelledError:
            self.error(tab, page, state["signal"], "interrupted", state)
            raise

    def interrupted(self, tab):
        record = self.attempts.get(tab)
        if record and record.get("finalRule") and record["outcome"] in {"waiting", "interrupted"}:
            return StealthishError(record["code"],
                                  message="Verification was interrupted. The site remains paused. No retry was made.",
                                  data={"verification": self.details(tab)})
        return None
