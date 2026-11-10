"""BotD and CreepJS result summaries. No standalone browser experiment."""


def detector_summary(results):
    summary = {}
    if "botd" in results:
        data = results["botd"]
        summary["botd"] = {"execution": data.get("status"), "verdict": data.get("verdict"),
                           "positiveDetections": [name for name, value in data.get("detections", {}).items() if value.get("bot")],
                           "unavailableSources": {name: value for name, value in data.get("components", {}).items() if value.get("state") != 0}}
    if "creepjs" in results:
        data = results["creepjs"]
        fp = data.get("fingerprint", {})
        summary["creepjs"] = {"execution": data.get("status"),
            "headless": fp.get("headless"), "lies": fp.get("lies"),
            "capturedErrors": fp.get("capturedErrors"), "trash": fp.get("trash"),
            "workerType": fp.get("workerScope", {}).get("type"),
            "networkAssessment": "BLOCKED_BY_POLICY: no STUN server result is available."}
    return summary
