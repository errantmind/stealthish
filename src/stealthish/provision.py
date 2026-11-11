"""Reconcile the extension's exact release pin before any browsing request."""
import json
from pathlib import Path
import re
import sys
import uuid

from .acquire import BROWSER_URL, BROWSER_SHA256, BLOCKER_URL, BLOCKER_SHA256
from .config import SessionConfig
from .errors import StartupError
from .maintenance import (MARKER, activate, prepare, recover, release_path, require_linux,
                          write_json)
from .ownership import ProfileLock
from .release import (VERSION, BROWSER_VERSION, BLOCKER_VERSION, DEPENDENCIES,
                      digest, load_release, verify_files)


def progress(stage):
    # Metadata only. The adapter supplies its own bounded user-facing messages.
    print(json.dumps({"setup": stage}), file=sys.stderr, flush=True)


def read_pin(path: Path, expected: str):
    if not re.fullmatch(r"[a-f0-9]{64}", expected) or digest(path) != expected:
        raise StartupError("RELEASE_INVALID")
    pin = json.loads(path.read_text())
    target = pin["targets"]["linux-x64"]
    if (pin["schemaVersion"] != 1 or pin["appVersion"] != VERSION
            or pin["protocolVersion"] != 1 or target["rendering"] != "linux-vulkan"
            or target["browser"] != {"version": BROWSER_VERSION, "url": BROWSER_URL,
                                      "sha256": BROWSER_SHA256}
            or pin["blocker"] != {"version": BLOCKER_VERSION, "url": BLOCKER_URL,
                                   "sha256": BLOCKER_SHA256}
            or {row["name"]: row["version"] for row in target["wheels"]} != DEPENDENCIES):
        raise StartupError("RELEASE_INVALID")
    py = pin["python"][target["python"]]
    if sys.version.split()[0] != f'{py["major"]}.{py["minor"]}.{py["patch"]}':
        raise StartupError("RELEASE_INVALID")
    return pin


def ensure(data_dir: Path, manifest: Path, expected: str):
    """Caller holds Pi's lease; this lock also excludes standalone owners.

    A repair creates a new immutable release. Never modify a selected release,
    downgrade a profile, reset blocker preferences, or replay a page operation.
    """
    require_linux()
    read_pin(manifest, expected)
    root = data_dir.expanduser().resolve()
    with ProfileLock(root) as lock:
        marker = root / MARKER
        if marker.exists():
            record = json.loads(marker.read_text())
            if not record.get("automaticSetup"):
                raise StartupError("MAINTENANCE_REQUIRED")
            # The marker prevented normal browsing after this setup began. Restore
            # only this interrupted setup's backup, not a later-use recovery pair.
            progress("restore-interrupted-setup")
            recover(root, accept_data_loss=True, _lock=lock)
        config_path = root / "config.toml"
        old = SessionConfig.load(data_dir=root) if config_path.exists() else None
        if old:
            old_manifest = json.loads((release_path(root, old.release) / "manifest.json").read_text())
            try:
                current_browser = tuple(int(x) for x in old_manifest["browserVersion"].split("."))
                wanted_browser = tuple(int(x) for x in BROWSER_VERSION.split("."))
            except (KeyError, TypeError, ValueError):
                raise StartupError("RELEASE_INVALID") from None
            if current_browser > wanted_browser:
                raise StartupError("PROFILE_DOWNGRADE_BLOCKED")
            if old_manifest.get("automaticSetup") == expected:
                try:
                    release = load_release(old)
                    verify_files(root / "blocker", release.metadata["files"]["blocker"], allow_metadata=True)
                    if not (root / "state/blocker.json").is_file():
                        raise StartupError("BLOCKER_SETUP_REQUIRED")
                    return {"code": "OK", "release": old.release, "appVersion": VERSION,
                            "changed": False, "python": str(release.root / "env/bin/python")}
                except StartupError as error:
                    if error.code != "RELEASE_INVALID":
                        raise
                    progress("repair-release")
        name = f"auto-{VERSION}-{expected[:8]}-{uuid.uuid4().hex[:8]}"
        progress("prepare-browser")
        prepare(root, name, _lock=lock)
        path = release_path(root, name) / "manifest.json"
        metadata = json.loads(path.read_text())
        metadata["automaticSetup"] = expected
        write_json(path, metadata)
        progress("activate-and-check-filtering")
        try:
            activate(root, name, _lock=lock, _automatic=expected)
        except BaseException:
            # Restore only a marker made by this activation. No page request has
            # been submitted. Keep failed state through the existing recovery path.
            if marker.exists():
                record = json.loads(marker.read_text())
                if record.get("automaticSetup") == expected and record.get("candidate") == name:
                    progress("restore-failed-setup")
                    recover(root, accept_data_loss=True, _lock=lock)
            raise
        return {"code": "OK", "release": name, "appVersion": VERSION,
                "changed": True, "python": str(release_path(root, name) / "env/bin/python")}
