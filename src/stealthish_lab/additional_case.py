"""Result assessment for the retained bot-detection integration checks."""

TEXT = "Local input checks preserve exact text. This is not a human-input adapter."
FPS_RULES = frozenset(("headlessChromeScreenResolution", "hasWebdriver", "hasWebdriverWritable",
    "hasSeleniumProperty", "hasCDP", "hasPlaywright", "hasImpossibleDeviceMemory", "hasHighCPUCount",
    "hasMissingChromeObject", "hasWebdriverIframe", "hasWebdriverWorker", "hasMismatchWebGLInWorker",
    "hasMismatchPlatformIframe", "hasMismatchPlatformWorker", "hasSwiftshaderRenderer", "hasUTCTimezone",
    "hasMismatchLanguages", "hasInconsistentEtsl", "hasBotUserAgent", "hasGPUMismatch", "hasPlatformMismatch"))
ASYNC_KEYS = ("isShaderF16Supported", "isCdpDetected", "isNotificationPermissionInconsistent",
              "isHighEntropyUserAgentDataMismatch", "isMissingMediaDevices", "isVoiceListInconsistent",
              "isWorkerInconsistent", "isWebDriverInWorker", "isWorkerWebGLInconsistent", "isCdpDetectedInWorker")


def unavailable(value, path=""):
    if isinstance(value, dict):
        return [row for key, child in value.items() for row in unavailable(child, path + "." + key)]
    if isinstance(value, list):
        return [row for index, child in enumerate(value) for row in unavailable(child, path + f"[{index}]")]
    if isinstance(value, str) and value in ("ERROR", "NA", "INIT", "SKIPPED"):
        return [{"path": path.lstrip("."), "value": value}]
    return []


def assess_fpscanner(state):
    raw = state.get("raw", {})
    rules = raw.get("fastBotDetectionDetails", {})
    valid = (state.get("status") == "DONE" and set(rules) == FPS_RULES and
             set(state.get("ruleNames", [])) == FPS_RULES and
             isinstance(raw.get("fastBotDetection"), bool) and
             all(isinstance(row.get("detected"), bool) for row in rules.values()))
    positive = [key for key, row in rules.items() if row.get("detected") is True]
    if valid and raw["fastBotDetection"] != bool(positive):
        valid = False
    signals = raw.get("signals", {})
    missing = unavailable(signals)
    worker = signals.get("contexts", {}).get("webWorker", {})
    absent_worker_fields = [k for k in ("userAgent", "platform", "memory", "cpuCount", "vendor", "renderer") if k not in worker]
    if absent_worker_fields or state.get("errors"):
        valid = False
    return {"execution": "PASS" if valid else "ERROR", "verdict": "ERROR" if not valid else
            "DETECTED" if positive else "NO_POSITIVE_IN_EXERCISED_CHECKS",
            "upstreamBotVerdict": raw.get("fastBotDetection"), "positiveDetections": positive,
            "ruleCount": len(rules), "missingRules": sorted(FPS_RULES - rules.keys()),
            "unavailableSignals": missing, "absentWorkerFields": absent_worker_fields,
            "coverage": "PARTIAL", "coverageNote": "Worker webdriver is not collected by this upstream worker; false detection is not proof of collection.",
            "workerWebdriverCollected": "webdriver" in worker,
            "ruleErrors": "Upstream rule exceptions become detected=false; they are not separately exposed."}


def signal_result(raw):
    valid = (isinstance(raw, dict) and isinstance(raw.get("isLegitClient"), bool) and
             isinstance(raw.get("suspicionScore"), (int, float)) and isinstance(raw.get("signals"), list) and bool(raw["signals"]) and
             all(isinstance(x.get("triggered"), bool) and isinstance(x.get("id"), str) for x in raw["signals"]) and
             len({x["id"] for x in raw["signals"]}) == len(raw["signals"]))
    return {"execution": "PASS" if valid else "ERROR", "isLegitClient": raw.get("isLegitClient"),
            "verdict": "ERROR" if not valid else "NO_BOT_BY_UPSTREAM_THRESHOLD" if raw["isLegitClient"] else "DETECTED",
            "suspicionScore": raw.get("suspicionScore"), "confidence": raw.get("confidence"),
            "signalCount": len(raw.get("signals", [])), "automation": raw.get("automation"),
            "positiveDetections": [x["id"] for x in raw.get("signals", []) if x.get("triggered")]}


def assess_bot_signal(state):
    sync, asynchronous, behavior = [signal_result(state.get(key, {})) for key in ("sync", "async", "behavior")]
    missing = [key for key in ASYNC_KEYS if key not in state.get("async", {})]
    omitted = [key for key in ASYNC_KEYS if state.get("async", {}).get(key) is None]
    counts = state.get("behavior", {}).get("sampleCounts", {})
    sampled = all(counts.get(k, 0) >= n for k, n in {"mouseMoves": 51, "scrolls": 8, "keyPresses": 20, "clicks": 2}.items())
    behavior.update({"sampleCounts": counts, "observationMs": state.get("behavior", {}).get("observationMs"),
                     "coverage": "DESKTOP_INPUT_SAMPLED" if sampled else "INCOMPLETE",
                     "notRun": ["touch", "human-input adapter", "manual-human reference"]})
    valid = (state.get("status") == "READY" and not state.get("errors") and not missing and
             all(x["execution"] == "PASS" for x in (sync, asynchronous, behavior)) and
             sync["signalCount"] == 39 and asynchronous["signalCount"] >= 39 and behavior["signalCount"] == 12 and
             sampled and state.get("elapsedMs", 0) >= 8000 and state.get("fieldValue") == TEXT and state.get("actionCount") == 2)
    return {"execution": "PASS" if valid else "ERROR", "sync": sync, "async": asynchronous,
            "behavioral": behavior, "missingAsyncChecks": missing, "unavailableAsyncChecks": omitted,
            "thresholds": {"static": 0.5, "behavioral": 0.55}, "coverage": "PARTIAL",
            "notRun": ["server IP/TLS/reputation", "production blocker configuration"],
            "inputCorrect": state.get("fieldValue") == TEXT and state.get("actionCount") == 2}


def assess_brotector(state):
    raw = state.get("raw", [])
    valid = (state.get("status") == "READY" and state.get("initComplete") is True and
             state.get("highEntropyCompleted") is True and isinstance(state.get("highEntropyValues"), dict) and
             isinstance(raw, list) and not state.get("errors") and
             state.get("events", {}).get("click", 0) >= 1 and state.get("events", {}).get("mousemove", 0) >= 1 and
             state.get("buttonText") == "Clicked :)")
    return {"execution": "PASS" if valid else "ERROR", "verdict": "ERROR" if not valid else
            "DETECTED" if raw else "NO_POSITIVE_IN_EXERCISED_CHECKS",
            "positiveDetections": sorted({x.get("detection", "UNKNOWN") for x in raw}),
            "detectionCount": len(raw), "coverage": "PARTIAL", "inputEvents": state.get("events"),
            "initComplete": state.get("initComplete"), "highEntropyCompleted": state.get("highEntropyCompleted"),
            "notRun": ["intentional crash probes", "Selenium injection", "canvas mouse visualization"],
            "scope": "Archived detector; absence of callbacks is not universal non-detection."}
