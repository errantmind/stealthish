"""Local BotD/CreepJS server. No general browser fixtures or remote fetching."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import urlsplit

from .concealment_fixtures import ACCEPT_CH, response


@contextmanager
def fixture_servers(root: Path, *, observations=None, script_gate=None):
    servers, threads = [], []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            path = urlsplit(self.path).path
            if script_gate is not None and not script_gate.allow(path):
                self.send_error(503, "Local detector gate failed")
                return
            found = response(root, path)
            data, content_type = found or (b"Not found", "text/plain")
            if observations is not None:
                observations.append({"path": self.path, "origin": self.server.origin,
                                     "headers": {k.lower(): v for k, v in self.headers.items()}})
            self.send_response(200 if found else 404)
            self.send_header("Accept-CH", ACCEPT_CH)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(data)
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
