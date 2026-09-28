# ruff: noqa: INP001, T201
"""Print every request it receives, to capture a real form builder's payload.

Used once, behind a tunnel, to see what Elementor Pro actually sends before an
adapter is written for it. Submit synthetic data only, and never commit a
capture that holds real personal data. See docs/integration/local-setup.md.

    python3 dev/capturar_webhook.py 8081
"""

import sys
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer

DEFAULT_PORT = 8081


class CaptureHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        print(f"\n--- {self.command} {self.path}")
        for name, value in self.headers.items():
            print(f"{name}: {value}")
        print()
        print(body.decode("utf-8", errors="replace"))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"capturado": true}')


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    print(f"Listening on http://localhost:{port}")
    HTTPServer(("127.0.0.1", port), CaptureHandler).serve_forever()
