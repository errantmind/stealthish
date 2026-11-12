"""Acquire a pinned official uBlock Origin Lite artifact without executing it."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
import zipfile
import io

ROOT = Path(__file__).resolve().parents[1]
TAG = "2026.1103.1743"
NAME = f"uBOLite_{TAG}.chromium.zip"


def main():
    release = json.loads(subprocess.check_output([
        "gh", "api", f"repos/uBlockOrigin/uBOL-home/releases/tags/{TAG}"
    ]))
    asset = next(x for x in release["assets"] if x["name"] == NAME)
    with urllib.request.urlopen(asset["browser_download_url"], timeout=60) as response:
        blob = response.read()
    digest = hashlib.sha256(blob).hexdigest()
    assert asset["digest"] == "sha256:" + digest
    base = ROOT / ".cache/blocker" / TAG
    base.mkdir(parents=True, exist_ok=True)
    (base / NAME).write_bytes(blob)
    directory = base / "extension"
    directory.mkdir(exist_ok=True)
    files = []
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        for item in archive.infolist():
            if item.is_dir():
                continue
            path = directory / item.filename
            assert path.resolve().is_relative_to(directory.resolve())
            assert not (item.external_attr >> 16) & 0o170000 == 0o120000
            data = archive.read(item)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            files.append({"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = json.loads((directory / "manifest.json").read_text())
    record = {"tag": TAG, "repository": "uBlockOrigin/uBOL-home", "releaseURL": release["html_url"],
              "assetURL": asset["browser_download_url"], "publisherDigest": asset["digest"],
              "archive": str((base / NAME).relative_to(ROOT)), "sha256": digest,
              "directory": str(directory.relative_to(ROOT)), "manifest": manifest, "files": files,
              "executed": False}
    (ROOT / "evidence/local/blocker-acquisition.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"tag": TAG, "sha256": digest, "files": len(files), "version": manifest['version']}, indent=2))


if __name__ == "__main__":
    main()
