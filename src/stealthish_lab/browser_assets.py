"""Verified browser choices for isolated experiments. No profile or system changes."""

import hashlib
import json
from pathlib import Path


def retail_manifest(root: Path) -> dict:
    path = root / "evidence/local/retail-chrome-acquisition.json"
    metadata = json.loads(path.read_text())
    base = root / ".cache/browsers/retail-chrome"
    if metadata.get("executable") != ".cache/browsers/retail-chrome/chrome":
        raise ValueError("Unexpected retail Chrome executable.")
    paths = [entry["path"] for entry in metadata["files"]]
    if metadata["executable"] not in paths or len(paths) != len(set(paths)):
        raise ValueError("The manifest must cover the executable and contain unique file paths.")
    for entry in metadata["files"]:
        item = (root / entry["path"]).resolve()
        if not item.is_relative_to(base) or not item.is_file():
            raise ValueError("A retail browser file is missing or outside the cache.")
        if hashlib.sha256(item.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Retail browser asset changed: " + entry["path"])
    return {"manifestSHA256": hashlib.sha256(path.read_bytes()).hexdigest(), **metadata}
