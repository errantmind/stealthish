"""Native careful input. ARIA handles are resolved by the owning driver."""
from ._vendor.human import patch_page_async, resolve_config
from .errors import StealthishError


class Input:
    def __init__(self):
        self.config = resolve_config("careful")

    def attach(self, page):
        if not hasattr(page._impl_obj, "_cloak_human"):
            patch_page_async(page, self.config)

    async def perform(self, page, params, ref=None, point=None):
        self.attach(page)
        action = params.get("action")
        if action not in {"click", "fill", "type", "press", "key", "hover", "scroll"}:
            raise StealthishError("UNSUPPORTED")
        if ref and params.get("selector"):
            raise StealthishError("INVALID_REQUEST")
        if point is not None:
            if action not in {"click", "hover"} or ref or params.get("selector"):
                raise StealthishError("INVALID_REQUEST")
            if action == "click":
                await page.mouse.click(*point)
            else:
                await page.mouse.move(*point)
            return
        if action == "type" and params.get("imageId") and not ref and not params.get("selector"):
            if not isinstance(params.get("text"), str):
                raise StealthishError("INVALID_REQUEST")
            await page.keyboard.type(params["text"])
            return
        handle = None
        try:
            if ref:
                handle = await page.locator("aria-ref=" + ref).element_handle()
                if handle is None:
                    raise StealthishError("STALE_REFERENCE")
                target = handle
            elif params.get("selector"):
                if not isinstance(params["selector"], str):
                    raise StealthishError("INVALID_REQUEST")
                target = page.locator(params["selector"])
            else:
                target = None
            if action in {"fill", "type", "press", "key"}:
                name = "text" if action in {"fill", "type"} else "key"
                if not isinstance(params.get(name), str):
                    raise StealthishError("INVALID_REQUEST")
            if action in {"click", "fill", "type", "hover", "press"} and target is None:
                raise StealthishError("INVALID_REQUEST")
            if action == "key":
                await page.keyboard.press(params["key"])
            elif action == "scroll":
                x, y = params.get("x", 0), params.get("y", 0)
                if any(type(n) not in {int, float} or not -10000 <= n <= 10000 for n in (x, y)):
                    raise StealthishError("INVALID_REQUEST")
                await page.mouse.wheel(x, y)
            elif action in {"click", "hover"}:
                await getattr(target, action)()
            elif action in {"fill", "type"}:
                if await target.get_attribute("type") == "color":
                    raise StealthishError("UNSUPPORTED")
                await getattr(target, action)(params["text"])
            else:
                await target.press(params["key"])
        finally:
            if handle is not None:
                await handle.dispose()
