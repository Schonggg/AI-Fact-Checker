"""Health check — Vercel Python function (diagnostic probe).

Uses the exact format from Vercel docs: class named `handler` that
extends BaseHTTPRequestHandler directly.
"""
from http.server import BaseHTTPRequestHandler


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok","service":"ai-fact-checker"}')

    def log_message(self, *args):
        pass
