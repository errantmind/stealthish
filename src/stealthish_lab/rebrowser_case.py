"""Rebrowser result assessment and its CSP controls."""
from collections import Counter

EXPECTED = frozenset(("dummyFn", "sourceUrlLeak", "mainWorldExecution", "runtimeEnableLeak",
    "exposeFunctionLeak", "navigatorWebdriver", "bypassCsp", "viewport", "useragent",
    "pwInitScripts", "headless", "platformMismatch", "workerConsistency", "nativeTampering",
    "mobileEmulation", "documentInterception", "popupBlocking", "ipcFloodingProtection",
    "storagePartitioning", "cdpBindingGlobals"))


def assess(rows, actions, observer, csp, *, stress):
    counts = Counter(row.get("type") for row in rows)
    missing, duplicates = sorted(EXPECTED - counts.keys()), sorted(k for k, v in counts.items() if v != 1)
    outcomes = []
    for row in rows:
        name, rating = row.get("type"), row.get("rating")
        status = {-1: "PASS", 0: "INCONCLUSIVE", 0.5: "WARNING", 1: "FAIL"}.get(rating, "ERROR")
        if name in ("sourceUrlLeak", "mainWorldExecution") and rating == 0:
            status = "NOT_TRIGGERED"
        if name == "exposeFunctionLeak" and not stress and rating == 0:
            status = "NOT_RUN"
        if name == "bypassCsp" and csp.get("status") != "PASS":
            status = "INCONCLUSIVE"
        outcomes.append({"name": name, "status": status, "upstreamRating": rating,
                         "note": row.get("note"), "debug": row.get("debug")})
    expected_actions = {"dummy-main-world": True, "source-url-default-world": "TEXTAREA", "main-world-default": 0}
    action_errors = [row for row in actions if row["status"] != "PASS" or
                     (row["name"] in expected_actions and row.get("result") != expected_actions[row["name"]])]
    errors = missing or duplicates or action_errors or not observer.get("runtime", {}).get("rounds")
    errors = bool(errors or any(row["status"] == "ERROR" for row in outcomes))
    failures = [row["name"] for row in outcomes if row["status"] == "FAIL" and row["name"] != "dummyFn"]
    incomplete = [row["name"] for row in outcomes if row["status"] in ("INCONCLUSIVE", "NOT_TRIGGERED", "NOT_RUN")]
    return {"execution": "ERROR" if errors else "PASS", "missing": missing, "duplicates": duplicates,
            "actionErrors": action_errors, "outcomes": outcomes, "positiveDetections": failures,
            "warnings": [row["name"] for row in outcomes if row["status"] == "WARNING"],
            "incomplete": incomplete, "verdict": "ERROR" if errors else "DETECTED" if failures else "NO_POSITIVE_IN_EXERCISED_CHECKS",
            "coverage": "PARTIAL" if incomplete or errors else "COMPLETE",
            "acceptance": "PENDING_USER_REVIEW", "productImplementationDecision": "REQUIRES_USER_APPROVAL",
            "scope": "Rebrowser has per-test ratings, not one commercial bot probability."}


async def csp_controls(context, origin, foreign):
    page = await context.new_page()
    try:
        await page.goto(origin + "/control/open")
        await page.wait_for_function("document.querySelector('#control-result')?.textContent === 'loaded'")
        unrestricted = await page.locator("#control-result").text_content()
        session = await context.new_cdp_session(page)
        await session.send("Page.setBypassCSP", {"enabled": True})
        await page.goto(origin + "/control/csp")
        await page.wait_for_function("document.querySelector('#control-result')?.textContent === 'loaded'")
        bypassed = await page.locator("#control-result").text_content()
        await session.detach()
        return {"status": "PASS", "unrestricted": unrestricted, "bypassed": bypassed,
                "target": foreign + "/csp-script.js", "scope": "Separate control page only."}
    finally:
        await page.close()
