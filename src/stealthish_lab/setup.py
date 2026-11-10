"""Disposable blocker setup and network isolation observer for detector runs."""
import asyncio
import json
import selectors
import socket
import threading
import time


async def initial_setup(config):
    # Only the detector's disposable profile is configured here.
    from stealthish.blocker import extension_call, RULESETS
    from stealthish.compatibility import select_driver, launch_options
    from stealthish.ownership import ProfileLock
    from stealthish.release import load_release, BLOCKER_VERSION
    from patchright.async_api import async_playwright
    with ProfileLock(config.data_dir):
        release = load_release(config)
        with select_driver(release):
            async with async_playwright() as runtime:
                context = await runtime.chromium.launch_persistent_context(
                    str(config.data_dir / "profile"), **launch_options(release))
                try:
                    cdp = await context.browser.new_browser_cdp_session()
                    eid = (await cdp.send("Extensions.loadUnpacked", {
                        "path": str(config.data_dir / "blocker")}))["id"]
                    await asyncio.sleep(1)
                    await extension_call(context, eid, '''async ids => {
                        await chrome.runtime.sendMessage({what:'applyRulesets',enabledRulesets:ids});
                        await chrome.runtime.sendMessage({what:'setDefaultFilteringMode',level:2});
                        for (const what of ['setAutoReload','setShowBlockedCount','setStrictBlockMode','setPopupBlockMode'])
                            await chrome.runtime.sendMessage({what,state:true});
                    }''', sorted(RULESETS))
                    (config.data_dir / "state/blocker.json").write_text(json.dumps({"id": eid, "version": BLOCKER_VERSION}))
                finally:
                    await context.close()


class HostCanary:
    """TCP and UDP observers on host loopback, outside the test network."""

    def __enter__(self):
        self.tcp = socket.socket()
        self.tcp.bind(("127.0.0.1", 0))
        self.tcp.listen()
        self.port = self.tcp.getsockname()[1]
        self.udp = socket.socket(type=socket.SOCK_DGRAM)
        self.udp.bind(("127.0.0.1", self.port))
        # Positive controls verify both listeners before isolated attempts.
        with socket.create_connection(("127.0.0.1", self.port), timeout=2):
            connection, _ = self.tcp.accept()
            connection.close()
        with socket.socket(type=socket.SOCK_DGRAM) as client:
            client.sendto(b"positive-control", ("127.0.0.1", self.port))
            self.udp.settimeout(2)
            assert self.udp.recv(100) == b"positive-control"
            self.udp.settimeout(None)
        self.received = {"tcp": 0, "udp": 0}
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.observe, daemon=True)
        self.thread.start()
        return self

    def observe(self):
        with selectors.DefaultSelector() as selector:
            selector.register(self.tcp, selectors.EVENT_READ, "tcp")
            selector.register(self.udp, selectors.EVENT_READ, "udp")
            while not self.stop.is_set():
                for key, _ in selector.select(timeout=0.1):
                    if key.data == "tcp":
                        connection, _ = self.tcp.accept()
                        connection.close()
                    else:
                        self.udp.recv(1024)
                    self.received[key.data] += 1

    def __exit__(self, *args):
        time.sleep(0.15)
        self.stop.set()
        self.thread.join(timeout=2)
        self.tcp.close()
        self.udp.close()
