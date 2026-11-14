"""Passive verification handling. No input, navigation, or extra web requests."""
import asyncio
from collections import deque
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from .errors import StealthishError
from .search import ENGINES, NO_RESULTS

WAIT_SECONDS = 10.0
POLL_SECONDS = 0.25
SAFE_ROUTES = {"/", "/search", "/turnstile", "/signin", "/login", "/sorry", "/captcha"}

# Runs in the driver's existing isolated world. Return classifications, not text.
INSPECT = r"""({containers, link, empty}) => {
    const visible=e => !!e && getComputedStyle(e).visibility!=='hidden' && e.getClientRects().length>0;
    const has=s => [...document.querySelectorAll(s)].some(visible);
    const results=containers && [...document.querySelectorAll(containers)].slice(0,100).some(e=>{
        const a=e.querySelector(link);
        return visible(e) && visible(a) && !!a.href && !!a.innerText.trim();
    });
    const main=document.querySelector('main,#search-results') || document.body;
    const text=main ? main.innerText.slice(0,100000).toLowerCase() : '';
    const noResults=!results && empty.some(s=>text.includes(s)) &&
        !has('h2 a[href], h3 a[href], a:has(h2), a:has(h3)');
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
    else if (!results && text.includes('our systems have detected unusual traffic'))
        found=signal('CHALLENGE_REQUIRED','unusual-traffic');
    else if (!results && text.includes('verify you are human to continue'))
        found=signal('CHALLENGE_REQUIRED','human-verification-text');
    return {signal:found,ready,searchReady:!!results || noResults};
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


def engine_for(url):
    host = urlsplit(url).hostname or ""
    return next((key for key, item in ENGINES.items()
                 if host == item["domain"] or host.endswith("." + item["domain"])), None)


@dataclass(frozen=True)
class Signal:
    code: str
    rule: str
    automatic: bool = False


async def inspect(page):
    url = page.url
    parsed = urlsplit(url)
    host, route = parsed.hostname or "", parsed.path.rstrip("/")
    engine = engine_for(url)
    info = ENGINES.get(engine, {})
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
        state = await page.evaluate(INSPECT, {"containers": info.get("containers"), "link": info.get("link"),
                                            "empty": NO_RESULTS.get(engine, [])})
    except Exception as error:
        # An automatic redirect can replace the document while it is observed.
        # This is an incomplete observation, not clearance or another navigation.
        if "Execution context was destroyed" not in str(error) and \
                "Cannot find context" not in str(error):
            raise
        return {"signal": route_signal, "ready": False, "searchReady": False, "url": url}
    signal = Signal(**state["signal"]) if state["signal"] else None
    if route_signal is not None:
        # A route or Turnstile frame is not proof that human input is required.
        if not route_signal.automatic or signal is None or signal.automatic or \
                signal.rule == "human-verification-text":
            signal = route_signal
    if page.url != url:
        state["ready"] = state["searchReady"] = False
    state.update(signal=signal, url=url)
    return state


class Verification:
    def __init__(self):
        self.navigation = {}
        self.attempts = {}
        self.deadline = 0.0
        self.wait_deadline = None
        self.search_engine = None

    def begin(self, deadline, search_engine=None):
        self.deadline = deadline
        self.wait_deadline = None
        self.search_engine = search_engine
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

    def record(self, tab, page, signal):
        now = asyncio.get_running_loop().time()
        record = self.attempts.setdefault(tab, {
            "started": now, "rule": signal.rule, "code": signal.code,
            "automatic": signal.automatic, "outcome": "waiting",
        })
        record.update(final=location(page.url), elapsedMs=round((now - record["started"]) * 1000),
                      navigation=list(self.navigation.get(tab, ())))
        return record

    def details(self, tab):
        record = self.attempts.get(tab)
        return {key: value for key, value in record.items() if key != "started"} if record else None

    def error(self, tab, page, signal, outcome):
        record = self.record(tab, page, signal)
        record.update(outcome=outcome, code=signal.code, finalRule=signal.rule)
        site = "Kagi" if (urlsplit(page.url).hostname or "").removeprefix("www.") == "kagi.com" else "The site"
        message = None
        if signal.code == "CHALLENGE_REQUIRED":
            if outcome == "human-required":
                message = f"{site} requests human verification. The site is paused. No retry was made."
            elif outcome == "interrupted":
                message = f"{site} verification was interrupted. The site remains paused. No retry was made."
            elif outcome == "still-present":
                message = f"{site} verification is still present. The site remains paused. No retry was made."
            else:
                duration = round(record["elapsedMs"] / 1000, 1)
                message = f"{site} verification did not complete within {duration:g} seconds. The site is paused. No retry was made."
        return StealthishError(signal.code, message=message, data={"verification": self.details(tab)})

    def ready(self, state, expected_url):
        if not state["ready"] or state["signal"] or urlsplit(state["url"]).scheme not in {"http", "https"}:
            return False
        if self.search_engine is None:
            return True
        expected = urlsplit(expected_url or ENGINES[self.search_engine]["url"])
        actual = urlsplit(state["url"])
        return engine_for(state["url"]) == self.search_engine and \
            actual.path.rstrip("/") == expected.path.rstrip("/") and state["searchReady"]

    async def check(self, tab, page, expected_url=None):
        state = await inspect(page)
        signal = state["signal"]
        if signal is None:
            return False
        if not signal.automatic:
            raise self.error(tab, page, signal, "human-required")
        loop = asyncio.get_running_loop()
        if self.wait_deadline is None:
            # Leave a small margin for returning the pause before the action timer.
            self.wait_deadline = min(loop.time() + WAIT_SECONDS, self.deadline - 0.1)
        self.record(tab, page, signal)
        try:
            async with asyncio.timeout_at(self.wait_deadline):
                while True:
                    await asyncio.sleep(POLL_SECONDS)
                    state = await inspect(page)
                    current = state["signal"]
                    if current is not None and not current.automatic:
                        raise self.error(tab, page, current, "human-required")
                    self.record(tab, page, signal)
                    if self.ready(state, expected_url):
                        self.attempts[tab]["outcome"] = "cleared"
                        return True
        except TimeoutError:
            raise self.error(tab, page, signal, "deadline") from None
        except asyncio.CancelledError:
            self.error(tab, page, signal, "interrupted")
            raise

    def interrupted(self, tab):
        record = self.attempts.get(tab)
        if record and record["outcome"] in {"waiting", "interrupted"}:
            return StealthishError(record["code"],
                                  message="Verification was interrupted. The site remains paused. No retry was made.",
                                  data={"verification": self.details(tab)})
        return None
