"""Pinned local detector artifacts with separate page-owned result adapters."""

from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

ASSETS = {
    "/fpscanner/bundle.js": ("fpscanner/dist/fpScanner.es.js", "text/javascript"),
    "/bot-signal/bundle.js": ("bot-signal/dist/browser.js", "text/javascript"),
    "/brotector/brotector.js": ("brotector/brotector.js", "text/javascript"),
    "/brotector/main.js": ("brotector/main.js", "text/javascript"),
    "/brotector/style.css": ("brotector/style.css", "text/css"),
    "/brotector/assets/test.pdf": ("brotector/assets/test.pdf", "application/pdf"),
}
ADAPTERS = {"/fpscanner/adapter.js": "fpscanner-adapter.js", "/bot-signal/adapter.js": "bot-signal-adapter.js",
            "/brotector/adapter.js": "brotector-adapter.js"}


def asset(root: Path, path: str):
    base = root / ".cache/detectors/additional"
    if path in ASSETS:
        name, mime = ASSETS[path]
        return (base / name).read_bytes(), mime
    if path in ADAPTERS:
        return (root / "fixtures" / ADAPTERS[path]).read_bytes(), "text/javascript"
    if path in ("/fpscanner/", "/bot-signal/"):
        return (root / "fixtures/additional-detector.html").read_text().replace("__ADAPTER__", path + "adapter.js").encode(), "text/html"
    if path == "/brotector/":
        data = (base / "brotector/index.html").read_text()
        if data.count("</body>") != 1:
            raise ValueError("Brotector document anchor changed")
        data = data.replace("</body>", '<pre id="lab-result"></pre><script src="adapter.js"></script></body>')
        return data.encode(), "text/html"
    return None


def verify_assets(root: Path):
    manifest = root / "evidence/local/additional-detector-acquisition.json"
    metadata = json.loads(manifest.read_text())
    entries = {row["path"]: row for row in metadata["files"]}
    required = [".cache/detectors/additional/" + name for name, _ in ASSETS.values()]
    required += [".cache/detectors/additional/brotector/index.html"]
    for name in required:
        if name not in entries:
            raise ValueError("A served detector asset is not recorded: " + name)
    for row in entries.values():
        path = (root / row["path"]).resolve()
        if not any(path.is_relative_to(root / folder) for folder in
                   (".cache/detectors/additional", "analysis/sources/additional-detectors")):
            raise ValueError("A detector asset is outside its source cache")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Detector asset changed: " + row["path"])
    return {"manifestSHA256": hashlib.sha256(manifest.read_bytes()).hexdigest(), **metadata}


@contextmanager
def additional_server(root: Path, observations: list):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def do_GET(self):
            response = asset(root, urlsplit(self.path).path)
            data, mime = response or (b"Not found", "text/plain")
            observations.append({"path": self.path, "status": 200 if response else 404,
                                 "sha256": hashlib.sha256(data).hexdigest()})
            self.send_response(200 if response else 404)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
