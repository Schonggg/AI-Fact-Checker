import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.verify import VerifyRequestHandler as VerifyHandler  # noqa: E402

# Static files (the frontend) live in public/. Serve from there so that
# GET / resolves to public/index.html, matching Vercel's static behaviour.
STATIC_DIR = ROOT / "public"


class LocalAppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_DIR), **kwargs)

    def _is_api_verify(self):
        return self.path.split("?", 1)[0] == "/api/verify"

    def do_OPTIONS(self):
        if self._is_api_verify():
            return VerifyHandler.do_OPTIONS(self)
        return super().do_OPTIONS()

    def do_POST(self):
        if self._is_api_verify():
            return VerifyHandler.do_POST(self)
        self.send_error(405, "POST is only supported on /api/verify")

    def do_GET(self):
        if self._is_api_verify():
            return VerifyHandler.do_GET(self)
        if self.path == "/":
            self.path = "/index.html"
        return super().do_GET()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "3000"))
    host = os.environ.get("HOST", "127.0.0.1")
    server = ThreadingHTTPServer((host, port), LocalAppHandler)
    print(f"GONKA Fact Checker running at http://{host}:{port}/")
    print(f"Frontend:  http://{host}:{port}/")
    print(f"API health: http://{host}:{port}/api/verify")
    server.serve_forever()
