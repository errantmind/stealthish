"""Prepare a disposable release for bot-detection integration checks only."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from stealthish.compatibility import adapt_driver  # noqa: E402
from stealthish.release import VERSION, BROWSER_VERSION, DRIVER_VERSION, BLOCKER_VERSION, DEPENDENCIES  # noqa: E402
from stealthish.ownership import private_directory  # noqa: E402
from stealthish.acquire import BROWSER_NAME, BROWSER_URL, BROWSER_SHA256, unpack_browser  # noqa: E402
from stealthish_lab.blocker import verify_assets  # noqa: E402


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def prepare(target):
    target = target.resolve()
    if not target.is_relative_to(ROOT / ".runtime") or target.exists():
        raise ValueError("Use a new, disposable directory inside .runtime.")
    archive = ROOT / ".cache/releases" / BROWSER_NAME
    if hashlib.sha256(archive.read_bytes()).hexdigest() != BROWSER_SHA256:
        raise ValueError("The official browser archive is missing or changed.")
    retail = {"url": BROWSER_URL, "sha256": BROWSER_SHA256}
    blocker = verify_assets(ROOT)
    private_directory(target)
    release = target / "releases/development"
    private_directory(release)
    for name in ("state", "profile", "artifacts", "recovery"):
        private_directory(target / name)
    unpack_browser(archive, release / "browser")
    shutil.copytree(ROOT / blocker["directory"], release / "blocker")
    shutil.copytree(release / "blocker", target / "blocker")
    package = Path(importlib.util.find_spec("patchright").origin).parent
    shutil.copytree(package / "driver/package", release / "driver/package")
    shutil.copy2(package / "driver/node", release / "driver/node")
    bundle = release / "driver/package/lib/coreBundle.js"
    bundle.write_bytes(adapt_driver(bundle.read_bytes()))
    manifest = {"schemaVersion": 1, "release": "development", "appVersion": VERSION,
                "platform": "linux", "architecture": "x86_64", "driverVersion": DRIVER_VERSION,
                "browserVersion": BROWSER_VERSION, "blockerVersion": BLOCKER_VERSION,
                "browserExecutable": "chrome", "dependencyVersions": DEPENDENCIES, "files": {k: hashes(release / k) for k in
                ("browser", "driver", "blocker")}, "runtimeFiles": hashes(ROOT / "src/stealthish"),
                "provenance": {"browser": retail, "blockerSource": blocker["sourceURL"]
                               if "sourceURL" in blocker else "https://github.com/uBlockOrigin/uBOL-home",
                               "limit": "Official HTTPS browser archive and pinned digest; no independent publisher signature."},
                "validation": {"status": "DEVELOPMENT_ONLY", "scope": "Local bot-detection integration checks",
                               "liveSites": "NOT_TESTED", "windows": "NOT_TESTED"}}
    (release / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (target / "config.toml").write_text(
        'schema_version = 1\nrelease = "development"\n'
        + "data_dir = " + json.dumps(str(target)) + '\nrendering = "linux-vulkan"\n')
    print("Prepared a development set. No profile was opened or blocker settings written.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path)
    prepare(parser.parse_args().target)
