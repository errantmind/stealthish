"""Load only the selected gorhill files. Startup validates rather than resets settings."""
import asyncio
import json

from .errors import StartupError
from .release import BLOCKER_VERSION, verify_files

RULESETS = {"ublock-filters", "easylist", "easyprivacy", "pgl", "ublock-badware", "urlhaus-full"}


async def extension_call(context, eid, expression, arg=None):
    page = await context.new_page()
    cdp = None
    try:
        await page.goto(f"chrome-extension://{eid}/dashboard.html", wait_until="domcontentloaded")
        cdp = await context.new_cdp_session(page)
        result = await cdp.send("Runtime.evaluate", {
            "expression": f"({expression})({json.dumps(arg)})", "awaitPromise": True, "returnByValue": True,
        })
        if "exceptionDetails" in result:
            raise StartupError("BLOCKER_UNAVAILABLE")
        return result["result"].get("value")
    finally:
        if cdp is not None:
            await cdp.detach()
        await page.close()


def validate_state(data):
    try:
        options = data["options"]
        valid = (data["version"] == BLOCKER_VERSION and not data["updateURL"]
                 and not data["imported"] and not data["developerMode"]
                 and set(data["enabledRulesets"]) == RULESETS
                 and options["defaultFilteringMode"] == 2 and options["hasOmnipotence"]
                 and "<all_urls>" in data["permissions"]["origins"]
                 and all(options[k] is True for k in
                         ("autoReload", "showBlockedCount", "strictBlockMode", "popupBlockMode"))
                 and all(job["name"] == "pruneCSSCache" for job in data["jobs"]))
        if not valid:
            raise ValueError()
    except (KeyError, TypeError, ValueError):
        raise StartupError("BLOCKER_UNAVAILABLE") from None


async def configure_blocker(context, config, release):
    """Explicit first installation only; never reset a configured profile."""
    marker = config.data_dir / "state/blocker.json"
    if marker.exists():
        raise StartupError("BLOCKER_SETUP_REQUIRED")
    verify_files(config.data_dir / "blocker", release.metadata["files"]["blocker"], allow_metadata=True)
    cdp = await context.browser.new_browser_cdp_session()
    try:
        eid = (await cdp.send("Extensions.loadUnpacked", {
            "path": str(config.data_dir / "blocker")}))["id"]
        await asyncio.sleep(1)
        await extension_call(context, eid, """async ids => {
            await chrome.runtime.sendMessage({what:'applyRulesets',enabledRulesets:ids});
            await chrome.runtime.sendMessage({what:'setDefaultFilteringMode',level:2});
            for (const what of ['setAutoReload','setShowBlockedCount','setStrictBlockMode','setPopupBlockMode'])
                await chrome.runtime.sendMessage({what,state:true});
        }""", sorted(RULESETS))
        with marker.open("x") as out:
            json.dump({"id": eid, "version": BLOCKER_VERSION}, out)
        marker.chmod(0o600)
    finally:
        await cdp.detach()


async def load_blocker(context, config, release):
    path = config.data_dir / "blocker"
    marker = config.data_dir / "state/blocker.json"
    if not marker.is_file():
        raise StartupError("BLOCKER_SETUP_REQUIRED")
    try:
        expected = json.loads(marker.read_text())
        verify_files(path, release.metadata["files"]["blocker"], allow_metadata=True)
        manifest = json.loads((path / "manifest.json").read_text())
        if manifest["version"] != BLOCKER_VERSION or manifest.get("update_url"):
            raise ValueError()
        cdp = await context.browser.new_browser_cdp_session()
        try:
            eid = (await cdp.send("Extensions.loadUnpacked", {"path": str(path)}))["id"]
        finally:
            await cdp.detach()
        if eid != expected["id"] or expected["version"] != BLOCKER_VERSION:
            raise ValueError()
        # Native registration can finish before the selected worker starts.
        await asyncio.sleep(1)
        state = await extension_call(context, eid, """async () => {
            const config=await chrome.runtime.sendMessage({what:'getCurrentConfig'});
            return {version:chrome.runtime.getManifest().version,
                updateURL:chrome.runtime.getManifest().update_url ?? null,
                options:await chrome.runtime.sendMessage({what:'getOptionsPageData'}),
                enabledRulesets:await chrome.declarativeNetRequest.getEnabledRulesets(),
                imported:await chrome.runtime.sendMessage({what:'getImportedLists'}),
                permissions:await chrome.permissions.getAll(), developerMode:config.developerMode,
                jobs:(await chrome.storage.local.get(['deferredJobs'])).deferredJobs ?? []};
        }""")
        validate_state(state)
        return eid
    except StartupError:
        raise
    except Exception:
        raise StartupError("BLOCKER_UNAVAILABLE") from None
