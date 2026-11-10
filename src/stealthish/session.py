"""One foreground owner and one active request. No service or queue."""
import asyncio
import contextlib
import secrets
import tempfile
from urllib.parse import urlsplit

from .blocker import configure_blocker, load_blocker
from .compatibility import identity_payload, launch_options, select_driver
from .config import SessionConfig
from .errors import StartupError, StealthishError
from .input import Input
from .localcheck import NATIVE, check_filtering, local_check_server
from .operations import challenge, execute
from .ownership import ProfileLock, private_directory
from .protocol import Request, Result
from .references import References
from .release import BROWSER_VERSION, load_release


class BrowserSession:
    def __init__(self, config: SessionConfig):
        self.config = config
        self._lock = ProfileLock(config.data_dir)
        self._maintenance = False
        self._initialize = False
        self._driver_selection = None
        self._runtime = None
        self._context = None
        self._busy = None
        self._ready = False
        self._closing = False
        self.pages = {}
        self.access, self.clock = {}, 0
        self.closed_tabs = []
        self.selected = None
        self.paused, self.pause_origins = {}, {}
        self.paused_sites = set()
        self.refs = References()
        self.input = Input()
        self.effect = "none"
        self._popup_tasks = set()

    async def _maintenance_open(self, lock, *, initialize=False):
        if lock.root != self.config.data_dir or lock.fd is None:
            raise StartupError("PROFILE_BUSY")
        self._lock = lock
        self._maintenance = True
        self._initialize = initialize
        return await self.__aenter__()

    async def __aenter__(self):
        if self._ready or self._runtime is not None:
            raise StartupError("SESSION_BUSY")
        if not self._maintenance:
            self._lock.acquire()
        try:
            self.release = load_release(self.config, _maintenance=self._maintenance)
            if not self._initialize and not (self.config.data_dir / "state/blocker.json").is_file():
                raise StartupError("BLOCKER_SETUP_REQUIRED")
            for name in ("profile", "artifacts"):
                private_directory(self.config.data_dir / name)
            self._driver_selection = select_driver(self.release)
            self._driver_selection.__enter__()
            from patchright.async_api import async_playwright
            self._runtime = await async_playwright().start()
            async with asyncio.timeout(120):
                await self._start_browser()
            self._ready = True
            return self
        except BaseException as error:
            await self.close()
            if isinstance(error, (StartupError, asyncio.CancelledError, KeyboardInterrupt)):
                raise
            raise StartupError("BROWSER_ERROR") from None

    async def _start_browser(self):
        # The native calibration profile contains synthetic local data only.
        with tempfile.TemporaryDirectory(prefix="calibrate-", dir=self.config.data_dir / "state") as path:
            with local_check_server() as (origin, token, receipts):
                calibration = await self._runtime.chromium.launch_persistent_context(
                    path, **launch_options(self.release))
                try:
                    if calibration.browser.version != BROWSER_VERSION:
                        raise StartupError("RELEASE_INVALID")
                    page = calibration.pages[0]
                    await page.goto(f"{origin}/{token}", wait_until="domcontentloaded")
                    payload = identity_payload(await page.evaluate(NATIVE))
                finally:
                    await calibration.close()
                self._context = await self._runtime.chromium.launch_persistent_context(
                    str(self.config.data_dir / "profile"),
                    **launch_options(self.release, payload, headless=self.config.headless))
                self._context.set_default_timeout(self.config.action_timeout * 1000)
                cdp = await self._context.browser.new_browser_cdp_session()
                try:
                    await cdp.send("Stealthish.setIdentity", payload)
                    if self._initialize:
                        await configure_blocker(self._context, self.config, self.release)
                        self._initialize = False
                    await load_blocker(self._context, self.config, self.release)
                    await check_filtering(self._context, origin, token, receipts)
                    if (await cdp.send("Stealthish.identityStatus"))["errors"]:
                        raise StartupError("INCOMPATIBLE_DRIVER")
                finally:
                    await cdp.detach()
        # Do not expose extension setup or local startup pages to callers.
        for page in list(self._context.pages):
            await page.close()
        self._context.on("page", self._page_added)
        await self.new_page()

    async def restart(self):
        # Ownership and the selected driver remain held throughout this transition.
        release = load_release(self.config)
        if release.metadata != self.release.metadata:
            raise StealthishError("RELEASE_INVALID")
        self.effect = "unknown"
        try:
            await self._context.close()
            self._context = None
            self.pages.clear()
            self.access.clear()
            self.closed_tabs.clear()
            self.selected = None
            self.refs = References()
            self.input = Input()
            self.paused.clear()
            self.pause_origins.clear()
            self.paused_sites.clear()
            await self._start_browser()
        except BaseException:
            # No partial session is offered after failed or cancelled restart.
            await self.close()
            raise

    def _page_added(self, page):
        if page in self.pages.values():
            return
        if len(self.pages) >= self.config.tab_limit and self.config.headless:
            if self.config.tab_policy == "strict":
                task = asyncio.create_task(page.close())
                self._popup_tasks.add(task)
                task.add_done_callback(self._popup_tasks.discard)
                return
            victim = self._victim()
            if victim:
                task = asyncio.create_task(self._evict(victim))
                self._popup_tasks.add(task)
                task.add_done_callback(self._popup_tasks.discard)
        tab = secrets.token_hex(12)
        self.pages[tab] = page
        self.touch(tab)
        if self.config.headless:
            self.input.attach(page)
        page.on("framenavigated", lambda _: self.refs.invalidate(tab))
        page.on("close", lambda: self._page_closed(tab))
        if self.selected is None:
            self.selected = tab

    def _page_closed(self, tab):
        self.pages.pop(tab, None)
        self.access.pop(tab, None)
        self.refs.invalidate(tab)
        self.paused.pop(tab, None)
        site = self.pause_origins.pop(tab, None)
        if site and site not in self.pause_origins.values():
            self.paused_sites.discard(site)
        if self.selected == tab:
            self.selected = max(self.pages, key=lambda key: self.access.get(key, 0), default=None)

    def touch(self, tab):
        self.clock += 1
        self.access[tab] = self.clock

    def _victim(self):
        candidates = [key for key in self.pages if key != self.selected]
        return min(candidates, key=lambda key: self.access.get(key, 0), default=None)

    async def _evict(self, tab):
        page = self.pages.get(tab)
        if page is not None:
            await page.close()
            self.closed_tabs.append(tab)
            self.closed_tabs = self.closed_tabs[-20:]

    async def new_page(self):
        if len(self.pages) >= self.config.tab_limit:
            victim = self._victim()
            if self.config.tab_policy != "lru" or victim is None:
                raise StealthishError("TAB_LIMIT")
            await self._evict(victim)
        page = await self._context.new_page()
        self._page_added(page)
        tab = next(key for key, value in self.pages.items() if value is page)
        self.selected = tab
        return tab, page

    def page(self, params):
        tab = params.get("tabId", self.selected)
        if not isinstance(tab, str) or tab not in self.pages or self.pages[tab].is_closed():
            raise StealthishError("TAB_NOT_FOUND")
        self.selected = tab
        self.touch(tab)
        return tab, self.pages[tab]

    def pause(self, tab, code, url):
        self.paused[tab] = code
        site = urlsplit(url).hostname
        self.pause_origins[tab] = site
        if site:
            self.paused_sites.add(site)
        self.refs.invalidate(tab)

    async def check_pause(self, tab, page, initiating_url=None):
        if tab in self.paused:
            raise StealthishError(self.paused[tab])
        if urlsplit(page.url).hostname in self.paused_sites:
            raise StealthishError("CHALLENGE_REQUIRED")
        reason = await challenge(page)
        if reason:
            self.pause(tab, reason, initiating_url or page.url)
            raise StealthishError(reason)

    async def execute(self, request: Request | dict) -> Result:
        if not isinstance(request, Request):
            request = Request.parse(request)
        if not self._ready:
            return Result(request.id, status="error", code="SESSION_CLOSED")
        if self._busy is not None:
            return Result(request.id, status="error", code="SESSION_BUSY")
        self._busy = asyncio.current_task()
        self.effect = "none"
        result = None
        try:
            timeout = self.config.action_timeout
            if request.operation in {"navigate", "tabs", "search"} and "timeoutMs" in request.params:
                value = request.params["timeoutMs"]
                if type(value) not in {int, float} or not 1 <= value <= 600000:
                    raise StealthishError("INVALID_REQUEST")
                timeout = max(timeout, value / 1000 + 20)
            async with asyncio.timeout(timeout):
                result = await execute(self, request)
            if self.closed_tabs:
                result.data["closedTabs"] = self.closed_tabs.copy()
                result.warnings.append("Inactive tabs were closed to retain the tab limit.")
                self.closed_tabs.clear()
        except asyncio.CancelledError:
            # Keep Python task cancellation. Never replay a partially sent action.
            raise
        except StealthishError as error:
            paused = error.code in {"CHALLENGE_REQUIRED", "AUTH_REQUIRED", "CONSENT_REQUIRED", "MANUAL_ACCESS"}
            result = Result(request.id, status="paused" if paused else "error", code=error.code,
                            effect=self.effect, data={"message": str(error)})
        except TimeoutError:
            result = Result(request.id, status="error", code="TIMEOUT", effect=self.effect)
        except Exception as error:
            from patchright.async_api import TimeoutError as DriverTimeout
            code = "TIMEOUT" if isinstance(error, DriverTimeout) else "BROWSER_ERROR"
            result = Result(request.id, status="error", code=code, effect=self.effect)
        finally:
            self._busy = None
        if request.operation == "close":
            await self.close()
        return result

    async def close(self):
        if self._closing:
            return
        self._closing = True
        self._ready = False
        try:
            if self._busy and self._busy is not asyncio.current_task():
                self._busy.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await self._busy
            for task in list(self._popup_tasks):
                task.cancel()
            if self._context:
                with contextlib.suppress(Exception):
                    async with asyncio.timeout(15):
                        await self._context.close()
            if self._runtime:
                with contextlib.suppress(Exception):
                    async with asyncio.timeout(15):
                        await self._runtime.stop()
        finally:
            self._context = self._runtime = None
            if self._driver_selection is not None:
                self._driver_selection.__exit__(None, None, None)
                self._driver_selection = None
            self.pages.clear()
            self.access.clear()
            self.closed_tabs.clear()
            self.selected = None
            self.paused.clear()
            self.pause_origins.clear()
            self.paused_sites.clear()
            self.refs = References()
            self._lock.close()
            self._closing = False

    async def __aexit__(self, *_):
        await self.close()
