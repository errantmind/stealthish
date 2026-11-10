"""Hold one local script response until the selected input world is ready.

This changes local response timing, not detector code or browser routing.
Both controls and candidates use the same gate. A timeout returns an error.
"""
import asyncio
from contextlib import contextmanager
import threading
import time


class ScriptGate:
    def __init__(self):
        self.active = None
        self.records = []

    @contextmanager
    def arm(self, path):
        if self.active is not None:
            raise RuntimeError("A script gate is already active.")
        record = {"path": path, "armedAt": time.monotonic(), "status": "PENDING"}
        state = {"record": record, "requested": threading.Event(), "release": threading.Event()}
        self.active = state
        self.records.append(record)
        try:
            yield state
        finally:
            state["release"].set()
            self.active = None

    def allow(self, path):
        state = self.active
        if state is None or path != state["record"]["path"]:
            return True
        state["record"].setdefault("requestedAt", time.monotonic())
        state["requested"].set()
        if not state["release"].wait(timeout=20):
            state["record"]["status"] = "ERROR"
            state["record"]["error"] = "The local script gate expired."
            return False
        allowed = state["record"]["status"] == "PASS"
        if allowed:
            state["record"].setdefault("responseAllowedAt", time.monotonic())
        return allowed


async def navigate_with_input_world(page, url, script_path, gate, adapter):
    """Start the unchanged collector only after input-helper initialization."""
    with gate.arm(script_path) as state:
        await page.goto(url, wait_until="commit", timeout=15000)
        if not await asyncio.to_thread(state["requested"].wait, 5):
            raise RuntimeError("The detector entry-script request was not observed.")
        if adapter:
            adapter.attach(page)
            # Use the upstream isolated-world installer. Do not touch page globals.
            human = page._impl_obj._cloak_human
            async with asyncio.timeout(10):
                value = await human.worlds.evaluate(page._impl_obj.main_frame, "true")
            if value is not True:
                raise RuntimeError("The input world did not initialize.")
            state["record"]["inputWorld"] = "READY"
        else:
            state["record"]["inputWorld"] = "NOT_INSTALLED_CONTROL"
        state["record"]["initializedAt"] = time.monotonic()
        state["record"]["status"] = "PASS"
        state["release"].set()
        await page.wait_for_load_state("load", timeout=25000)
        state["record"]["loadedAt"] = time.monotonic()
    return dict(state["record"])


async def native_probe_input(page, adapter, selector=None):
    """The same small input task for both modes. No detector-specific timings."""
    if adapter:
        await adapter.action(page.mouse.move(40, 80))
        if selector:
            await adapter.action(page.locator(selector).click())
    else:
        await page.mouse.move(40, 80)
        if selector:
            await page.locator(selector).click()
    return {"status": "PASS", "move": [40, 80], "clickSelector": selector,
            "mode": "mit-careful" if adapter else "ordinary"}
