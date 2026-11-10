"""Local Rebrowser assets. Only dependency URLs and observation output are adapted."""

from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

RELEASE_URL = "https://chromiumdash.appspot.com/fetch_releases?channel=Stable&platform=Windows&num=1&offset=0"
CSP_URL = "https://www.w3schools.com/js/myScript.js"
CSP = "default-src * data: 'unsafe-eval' 'unsafe-inline' blob:; script-src blob: 'self' 'unsafe-eval' 'unsafe-inline' https://static.cloudflareinsights.com https://cloudflareinsights.com;"
ROUTES = {"/": "index.html", "/index.js": "index.js", "/index.css": "index.css",
          "/aba/mid/": "aba/mid/index.html", "/aba/leaf/": "aba/leaf/index.html",
          "/releases.json": "releases.json"}

OBSERVER = """const output = document.querySelector('#lab-observer');
const state = {violations:[]};
function publish() {
  state.runtime = window.runtimeEnableLeakVars ? {...window.runtimeEnableLeakVars} : null;
  state.optionalInit = window.__labOptionalInitRan === true;
  state.exposedFunctionPresent = typeof window.exposedFn === 'function';
  state.elapsed = performance.now();
  output.textContent = JSON.stringify(state);
}
addEventListener('securitypolicyviolation', event => {
  state.violations.push({blockedURI:event.blockedURI, directive:event.effectiveDirective,
                        disposition:event.disposition}); publish();
});
setInterval(publish, 250); publish();
"""
SCRIPT = "const node=document.querySelector('#control-result'); if(node) node.textContent='loaded';"


def asset(root: Path, path: str, foreign: str):
    cache = root / ".cache/detectors/rebrowser"
    mime = "text/html; charset=utf-8"
    if path in ROUTES:
        data = (cache / ROUTES[path]).read_text()
        if path == "/index.js":
            if data.count(RELEASE_URL) != 1 or data.count(CSP_URL) != 1:
                raise ValueError("Rebrowser dependency anchors changed.")
            data = data.replace(RELEASE_URL, "/releases.json").replace(CSP_URL, foreign + "/csp-script.js")
            mime = "text/javascript; charset=utf-8"
        elif path == "/":
            if CSP not in data or data.count("</body>") != 1:
                raise ValueError("Rebrowser document anchors changed.")
            data = data.replace("</body>", '<pre id="lab-observer"></pre><script src="/lab-observer.js"></script></body>')
        elif path.endswith(".css"):
            mime = "text/css"
        elif path.endswith(".json"):
            mime = "application/json"
        return data, mime
    if path == "/lab-observer.js":
        return OBSERVER, "text/javascript"
    if path == "/csp-script.js":
        return SCRIPT, "text/javascript"
    if path in ("/control/open", "/control/csp"):
        meta = f'<meta http-equiv="Content-Security-Policy" content="{CSP}">' if path.endswith("csp") else ""
        return (f'<!doctype html><html><head>{meta}</head><body><pre id="control-result">pending</pre>'
                f'<script src="{foreign}/csp-script.js"></script></body></html>'), mime
    return None


@contextmanager
def rebrowser_servers(root: Path, observations: list, *, script_gate=None):
    servers, threads = [], []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format, *args):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            if script_gate is not None and not script_gate.allow(path):
                self.send_error(503, "Local test gate failed")
                return
            response = asset(root, path, servers[1].origin)
            data, mime = response or ("Not found", "text/plain")
            raw = data.encode()
            observations.append({"path": self.path, "host": self.headers.get("Host"),
                                 "origin": self.server.origin, "status": 200 if response else 404,
                                 "sha256": hashlib.sha256(raw).hexdigest()})
            self.send_response(200 if response else 404)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

    try:
        for address in ("127.0.0.1", "127.0.0.2"):
            server = ThreadingHTTPServer((address, 0), Handler)
            server.daemon_threads = True
            server.origin = f"http://{address}:{server.server_port}"
            servers.append(server)
        for server in servers:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            threads.append(thread)
        yield servers[0].origin, servers[1].origin
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        for thread in threads:
            thread.join(timeout=3)


def verify_assets(root: Path):
    manifest_path = root / "evidence/local/rebrowser-acquisition.json"
    metadata = json.loads(manifest_path.read_text())
    for row in metadata["files"]:
        path = (root / row["path"]).resolve()
        if not path.is_relative_to(root / ".cache/detectors/rebrowser"):
            raise ValueError("A detector asset is outside its cache.")
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise ValueError("Rebrowser asset integrity failed: " + row["path"])
    return {"manifestSHA256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(), **metadata}
