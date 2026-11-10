"""Short-lived loopback fixtures for startup validation. No control endpoint."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import secrets
import threading

from .errors import StartupError

NATIVE = """async () => ({userAgent:navigator.userAgent,platform:navigator.platform,
clientHints:await navigator.userAgentData.getHighEntropyValues([
'architecture','bitness','model','platformVersion','fullVersionList','uaFullVersion','wow64','formFactors'])})"""


@contextmanager
def local_check_server():
    token = secrets.token_hex(16)
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            if token not in self.path:
                self.send_error(404)
                return
            seen.append(self.path)
            script = self.path.startswith(("/ads/", "/allowed/"))
            body = b"void 0;" if script else b"<!doctype html><title>Local startup check</title>"
            self.send_response(200)
            self.send_header("Content-Type", "application/javascript" if script else "text/html")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", token, seen
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


async def check_filtering(context, origin, token, seen):
    page = await context.new_page()
    try:
        await page.goto(f"{origin}/{token}", wait_until="domcontentloaded")
        paths = [f"/ads/!rotator/{token}.js", f"/allowed/{token}.js"]
        before = len(seen)
        values = await page.evaluate("""async paths => Promise.all(paths.map(async path => {
            try {return (await fetch(path, {cache:'no-store'})).ok;} catch {return false;}
        }))""", paths)
        if values != [False, True] or paths[0] in seen[before:] or paths[1] not in seen[before:]:
            raise StartupError("BLOCKER_UNAVAILABLE")
    finally:
        await page.close()
