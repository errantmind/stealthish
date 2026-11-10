"""Copy installed Chrome program files into the lab. Do not copy any user profile."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import stat
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("/opt/google/chrome")
DESTINATION = ROOT / ".cache/browsers/retail-chrome"


def main():
    package = subprocess.check_output(["pacman", "-Q", "google-chrome"], text=True).strip()
    if DESTINATION.exists():
        raise RuntimeError("The isolated copy already exists. Do not overwrite reviewed assets.")
    if any(p.is_symlink() for p in SOURCE.rglob("*")):
        raise ValueError("Review program symlinks before acquisition.")
    shutil.copytree(SOURCE, DESTINATION)
    files = []
    for path in sorted(DESTINATION.rglob("*")):
        if not path.is_file():
            continue
        # Do not retain set-user-ID or set-group-ID bits in the isolated copy.
        path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o6000)
        files.append({"path": str(path.relative_to(ROOT)),
                      "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    manifest = {"capturedAt": datetime.now(timezone.utc).isoformat(), "package": package,
                "source": str(SOURCE), "executable": str((DESTINATION / "chrome").relative_to(ROOT)),
                "files": files, "profileAccess": False, "executed": False,
                "provenanceLimit": "Installed package and local hashes; no independent publisher signature check.",
                "scope": "Private local no-blocker browser comparison. Not a production selection."}
    path = ROOT / "evidence/local/retail-chrome-acquisition.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print("Copied", len(files), "program files from", package, "without execution or profile access.")


if __name__ == "__main__":
    main()
