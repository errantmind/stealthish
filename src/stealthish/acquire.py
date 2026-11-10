"""Explicit acquisition of the selected published Linux browser and gorhill package."""
import io
import json
from pathlib import Path
import shutil
import stat
import tarfile
import urllib.request
import zipfile

from .errors import StartupError
from .ownership import private_directory
from .release import BROWSER_VERSION, BLOCKER_VERSION, child, digest

BROWSER_NAME = f"google-chrome-stable_{BROWSER_VERSION}-1_amd64.deb"
BROWSER_URL = "https://dl.google.com/linux/chrome/deb/pool/main/g/google-chrome-stable/" + BROWSER_NAME
BROWSER_SHA256 = "be1a1e161419f5c8272432f6860912550d8e29985e925913fa800493a0d0c955"
BLOCKER_NAME = f"uBOLite_{BLOCKER_VERSION}.chromium.zip"
BLOCKER_URL = f"https://github.com/uBlockOrigin/uBOL-home/releases/download/{BLOCKER_VERSION}/{BLOCKER_NAME}"
BLOCKER_SHA256 = "79236476535b63706749e088e0ce99bb31d3d2ff15fabb4d7e990be23d6e4613"


def download(directory, name, url, expected):
    private_directory(directory)
    target = child(directory, name)
    if target.exists():
        if digest(target) != expected:
            raise StartupError("ACQUISITION_FAILED")
        return target
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as source, temporary.open("xb") as out:
            if not source.url.startswith("https://"):
                raise StartupError("ACQUISITION_FAILED")
            size = 0
            while data := source.read(1024 * 1024):
                size += len(data)
                if size > 500_000_000:
                    raise StartupError("ACQUISITION_FAILED")
                out.write(data)
        temporary.chmod(0o600)
        if digest(temporary) != expected:
            raise StartupError("ACQUISITION_FAILED")
        temporary.replace(target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return target


def unpack_browser(archive: Path, target: Path):
    # Read only the Debian data member; do not execute package installation scripts.
    with archive.open("rb") as source:
        if source.read(8) != b"!<arch>\n":
            raise StartupError("ACQUISITION_FAILED")
        while header := source.read(60):
            if len(header) != 60 or header[58:] != b"`\n":
                raise StartupError("ACQUISITION_FAILED")
            size = int(header[48:58])
            if not 0 < size <= 500_000_000:
                raise StartupError("ACQUISITION_FAILED")
            name = header[:16].decode("ascii").strip().rstrip("/")
            if name.startswith("data.tar"):
                payload = source.read(size)
                break
            source.seek(size + size % 2, 1)
        else:
            raise StartupError("ACQUISITION_FAILED")
    private_directory(target)
    prefix = "opt/google/chrome/"
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:*") as package:
        total = 0
        for item in package:
            name = item.name.removeprefix("./")
            if not name.startswith(prefix) or name == prefix:
                continue
            path = child(target, name[len(prefix):])
            if item.isdir():
                private_directory(path)
                continue
            if not item.isfile():
                raise StartupError("ACQUISITION_FAILED")
            total += item.size
            if total > 1_500_000_000:
                raise StartupError("ACQUISITION_FAILED")
            private_directory(path.parent)
            with package.extractfile(item) as source, path.open("xb") as out:
                shutil.copyfileobj(source, out)
            path.chmod(0o700 if item.mode & 0o111 else 0o600)
    if not (target / "chrome").is_file():
        raise StartupError("ACQUISITION_FAILED")


def unpack_blocker(archive: Path, target: Path):
    private_directory(target)
    with zipfile.ZipFile(archive) as package:
        if sum(item.file_size for item in package.infolist()) > 500_000_000:
            raise StartupError("ACQUISITION_FAILED")
        for item in package.infolist():
            path = child(target, item.filename.rstrip("/"))
            if stat.S_ISLNK(item.external_attr >> 16):
                raise StartupError("ACQUISITION_FAILED")
            if item.is_dir():
                private_directory(path)
                continue
            private_directory(path.parent)
            with package.open(item) as source, path.open("xb") as out:
                shutil.copyfileobj(source, out)
            path.chmod(0o600)
    metadata = json.loads((target / "manifest.json").read_text())
    if metadata["version"] != BLOCKER_VERSION or metadata.get("update_url"):
        raise StartupError("ACQUISITION_FAILED")


def acquire(downloads: Path, release: Path):
    browser = download(downloads, BROWSER_NAME, BROWSER_URL, BROWSER_SHA256)
    blocker = download(downloads, BLOCKER_NAME, BLOCKER_URL, BLOCKER_SHA256)
    unpack_browser(browser, release / "browser")
    unpack_blocker(blocker, release / "blocker")
    return {
        "browser": {"url": BROWSER_URL, "sha256": BROWSER_SHA256,
                    "verification": "Official HTTPS distribution and pinned digest; no independent publisher signature."},
        "blocker": {"url": BLOCKER_URL, "sha256": BLOCKER_SHA256,
                    "verification": "Official upstream release; pinned published SHA-256 digest."},
    }
