"""Acquire the pinned MIT input modules. Do not import or execute them."""
import base64
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
REVISION = "b860957b1299967e1f0226b629b1da2d36e53c82"
MODULES = ("__init__", "config", "engine", "errors", "fields", "injected", "keyboard", "mouse", "patch", "world")


def main():
    cache = ROOT / ".cache/human-input/0.6.5"
    cache.mkdir(parents=True, exist_ok=True)
    rows = []
    for source in ["LICENSE", *[f"cloakbrowser/human/{name}.py" for name in MODULES]]:
        data = json.loads(subprocess.check_output([
            "gh", "api", f"repos/CloakHQ/CloakBrowser/contents/{source}?ref={REVISION}"
        ]))
        blob = base64.b64decode(data["content"])
        path = cache / Path(source).name
        if path.exists() and path.read_bytes() != blob:
            raise RuntimeError("The existing input cache differs. Stop for review.")
        path.write_bytes(blob)
        rows.append({"path": str(path.relative_to(ROOT)), "source": source,
                     "sha256": hashlib.sha256(blob).hexdigest(), "url": data["html_url"]})
    manifest = {"repository": "CloakHQ/CloakBrowser", "revision": REVISION, "version": "0.6.5",
                "license": "MIT", "files": rows,
                "boundary": "Human-input source and license only. No package initializer, browser, downloader, or key code."}
    (ROOT / "evidence/local/human-input-acquisition.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Acquired {len(rows)} files. No source was executed.")


if __name__ == "__main__":
    main()
