"""Build local publication assets. Never commit, tag, upload, or publish.

Run with Python 3.14 and packaging==26.0. Build the application wheel first.
Only the measured Linux target is selected. Installer metadata for other
systems is retained, but does not declare those browser targets supported.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tomllib
from urllib.parse import unquote, urlparse
import zipfile

from packaging.tags import cpython_tags, compatible_tags
from packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from stealthish.acquire import BROWSER_URL, BROWSER_SHA256, BLOCKER_URL, BLOCKER_SHA256  # noqa: E402
from stealthish.compatibility import SOURCE_SHA256  # noqa: E402
from stealthish.release import VERSION, BROWSER_VERSION, BLOCKER_VERSION, DEPENDENCIES  # noqa: E402


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(wheel, output):
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    lock = tomllib.loads((ROOT / "uv.lock").read_text())
    if project["project"]["version"] != VERSION or wheel.name != f"stealthish-{VERSION}-py3-none-any.whl":
        raise ValueError("Build the current application wheel first.")
    with zipfile.ZipFile(wheel) as archive:
        for source in (ROOT / "src/stealthish").rglob("*"):
            if source.is_file() and "__pycache__" not in source.parts:
                if archive.read("stealthish/" + source.relative_to(ROOT / "src/stealthish").as_posix()) != source.read_bytes():
                    raise ValueError("The wheel differs from the current source.")
        if any(name.startswith("stealthish_lab/") for name in archive.namelist()):
            raise ValueError("The wheel contains research code.")
    # Choose compatible binary wheels for a declared glibc floor, not whatever
    # higher glibc happens to be installed on the release builder's host.
    platforms = [f"manylinux_2_{v}_x86_64" for v in range(31, 4, -1)]
    platforms += ["manylinux2014_x86_64", "manylinux2010_x86_64", "manylinux1_x86_64"]
    tags = [*cpython_tags((3, 14), platforms=platforms),
            *compatible_tags((3, 14), interpreter="cp314", platforms=platforms)]
    rank = {tag: i for i, tag in enumerate(tags)}
    packages = {p["name"]: p for p in lock["package"]}
    wheels = []
    for name, version in DEPENDENCIES.items():
        package = packages[name]
        if package["version"] != version:
            raise ValueError("Runtime dependency differs from uv.lock: " + name)
        choices = []
        for row in package.get("wheels", []):
            filename = unquote(urlparse(row["url"]).path.rsplit("/", 1)[1])
            _, _, _, supported = parse_wheel_filename(filename)
            order = min((rank[t] for t in supported if t in rank), default=None)
            if order is not None:
                choices.append((order, filename, row))
        if not choices:
            raise ValueError("No locked binary wheel for " + name)
        _, filename, row = min(choices)
        wheels.append({"name": name, "version": version, "filename": filename,
                       "url": row["url"], "sha256": row["hash"].removeprefix("sha256:")})
    tools = json.loads((ROOT / "distribution/bootstrap-tools.json").read_text())
    base = f"https://github.com/errantmind/stealthish/releases/download/v{VERSION}/"
    record = {
        "schemaVersion": 1, "appVersion": VERSION, "protocolVersion": 1,
        "app": {"filename": wheel.name, "url": base + wheel.name, "sha256": sha(wheel)},
        **tools,
        "blocker": {"version": BLOCKER_VERSION, "url": BLOCKER_URL, "sha256": BLOCKER_SHA256},
        "driverSourceSha256": SOURCE_SHA256,
        "targets": {"linux-x64": {
            "minimumGlibc": "2.31", "rendering": "linux-vulkan",
            "scope": "Linux x86-64 desktop with native libraries and a working Vulkan GPU. Measured on NVIDIA.",
            "python": "cpython-3.14.9-linux-x86_64-gnu", "wheels": wheels,
            "browser": {"version": BROWSER_VERSION, "url": BROWSER_URL, "sha256": BROWSER_SHA256},
        }},
    }
    output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(wheel, output / wheel.name)
    manifest = output / "stealthish-release.json"
    manifest.write_text(json.dumps(record, indent=2) + "\n")
    pin = {"schemaVersion": 1, "manifest": {"url": base + manifest.name, "sha256": sha(manifest)}}
    (output / "stealthish-pin.json").write_text(json.dumps(pin, indent=2) + "\n")
    print(json.dumps({"output": str(output), "version": VERSION, "manifest": pin["manifest"],
                      "publish": [manifest.name, wheel.name], "uploaded": False}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build(args.wheel.resolve(), args.output.resolve())
