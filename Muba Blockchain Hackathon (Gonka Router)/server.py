import os
import sys
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from api.verify import VerifyRequestHandler as VerifyHandler  # noqa: E402


class LocalAppHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

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
    server = ThreadingHTTPServer(("127.0.0.1", port), LocalAppHandler)
    print(f"GONKA Fact Checker running at http://127.0.0.1:{port}/index.html")
    print("API health: http://127.0.0.1:{}/api/verify".format(port))
    server.serve_forever()
