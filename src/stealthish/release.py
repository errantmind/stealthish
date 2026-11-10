"""Read and verify a selected local release. No download or activation code."""
from dataclasses import dataclass
import hashlib
from importlib.metadata import version
import json
from pathlib import Path, PurePosixPath
import platform
import re
import sys

from .errors import StartupError

VERSION = "0.1.0.dev5"
DRIVER_VERSION = "1.64.4"
DEPENDENCIES = {
    "patchright": DRIVER_VERSION, "greenlet": "3.5.6", "pyee": "14.0.0", "typing-extensions": "4.16.0",
    "trafilatura": "2.3.1", "babel": "2.18.0", "certifi": "2026.10.23", "charset-normalizer": "3.5.2",
    "courlan": "1.4.0", "dateparser": "1.5.0", "htmldate": "1.11.0", "justext": "3.0.2",
    "lxml": "6.1.3", "lxml-html-clean": "0.4.6", "python-dateutil": "4.0.0", "pytz": "2026.6",
    "regex": "2026.11.9", "tld": "0.13.2", "tzdata": "2026.6", "tzlocal": "5.4.5", "urllib3": "2.8.0",
}
BROWSER_VERSION = "156.0.8078.79"
BLOCKER_VERSION = "2026.1103.1743"


def digest(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def child(root: Path, name: str) -> Path:
    if not isinstance(name, str) or "\\" in name or ":" in name:
        raise StartupError("RELEASE_INVALID")
    parts = PurePosixPath(name)
    if parts.is_absolute() or not parts.parts or any(x in {".", ".."} for x in parts.parts):
        raise StartupError("RELEASE_INVALID")
    path = root / name
    if not path.resolve().is_relative_to(root.resolve()) or any(
        item.is_symlink() for item in [path, *path.parents] if item != root.parent
    ):
        raise StartupError("RELEASE_INVALID")
    return path


def verify_files(root: Path, files: dict, *, allow_metadata=False, ignore_bytecode=False):
    if not isinstance(files, dict) or not files:
        raise StartupError("RELEASE_INVALID")
    for name, expected in files.items():
        path = child(root, name)
        if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise StartupError("RELEASE_INVALID")
        if not path.is_file() or digest(path) != expected:
            raise StartupError("RELEASE_INVALID")
    actual = set()
    for path in root.rglob("*"):
        if ignore_bytecode and ("__pycache__" in path.parts or path.suffix == ".pyc"):
            continue
        if path.is_symlink():
            raise StartupError("RELEASE_INVALID")
        if path.is_file():
            name = path.relative_to(root).as_posix()
            if allow_metadata and name.startswith("_metadata/"):
                continue
            actual.add(name)
    if actual != set(files):
        raise StartupError("RELEASE_INVALID")


@dataclass(frozen=True)
class Release:
    root: Path
    metadata: dict

    @property
    def executable(self):
        return child(self.root / "browser", self.metadata["browserExecutable"])

    @property
    def node(self):
        return self.root / "driver/node"


def load_release(config, *, _maintenance=False) -> Release:
    try:
        if not _maintenance and (config.data_dir / "state/maintenance-in-progress.json").exists():
            raise StartupError("MAINTENANCE_REQUIRED")
        root = child(config.data_dir / "releases", config.release)
        data = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        expected = {"schemaVersion", "release", "appVersion", "platform", "architecture",
                    "driverVersion", "browserVersion", "blockerVersion", "browserExecutable",
                    "files", "runtimeFiles", "dependencyVersions", "provenance", "validation"}
        environment = {"environmentPath", "environmentFiles", "pythonVersion"}
        if (set(data) not in (expected, expected | environment)
                or data["schemaVersion"] != 1 or data["release"] != config.release):
            raise ValueError()
        if environment <= data.keys():
            if data["pythonVersion"] != sys.version.split()[0]:
                raise ValueError()
            verify_files(child(root, data["environmentPath"]), data["environmentFiles"], ignore_bytecode=True)
        if data["dependencyVersions"] != DEPENDENCIES or any(
            version(name) != expected for name, expected in DEPENDENCIES.items()
        ):
            raise ValueError()
        if (data["appVersion"] != VERSION or data["driverVersion"] != DRIVER_VERSION
                or version("patchright") != DRIVER_VERSION or data["browserVersion"] != BROWSER_VERSION
                or data["blockerVersion"] != BLOCKER_VERSION):
            raise ValueError()
        if sys.platform != "linux" or data["platform"] != "linux" or platform.machine() != data["architecture"]:
            raise StartupError("UNSUPPORTED_PLATFORM")
        if data["architecture"] != "x86_64" or config.rendering != "linux-vulkan":
            raise StartupError("UNSUPPORTED_PLATFORM")
        if set(data["files"]) != {"browser", "driver", "blocker"}:
            raise ValueError()
        for area, entries in data["files"].items():
            verify_files(root / area, entries)
        # Code bytes must match the selected release, including vendored input.
        package = Path(__file__).parent
        actual = {p.relative_to(package).as_posix() for p in package.rglob("*")
                  if p.is_file() and "__pycache__" not in p.parts}
        if actual != set(data["runtimeFiles"]):
            raise ValueError()
        for name, expected_hash in data["runtimeFiles"].items():
            if digest(child(package, name)) != expected_hash:
                raise ValueError()
        for key in ("provenance", "validation"):
            if not isinstance(data[key], dict) or not data[key]:
                raise ValueError()
        release = Release(root, data)
        if not release.executable.is_file() or not release.node.is_file():
            raise ValueError()
        return release
    except (ValueError, TypeError, KeyError, OSError):
        raise StartupError("RELEASE_INVALID") from None
