#!/usr/bin/env python3
"""Dev server for the companion art tools.

Serves the marina repo root (so the baker can load app/models/model.vrm and
the app's three.js bundle) and accepts POST /save/<name>.png, writing the
body into aiws/companion/frames/marina/. Localhost only.

  python3 aiws/companion/serve.py [port]
"""
import http.server
import os
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "frames" / "marina"
NAME = re.compile(r"^[a-z0-9_-]+\.(png|json)$")


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=str(REPO), **kw)

    def do_POST(self):
        m = re.match(r"^/save/(.+)$", self.path)
        if not m or not NAME.match(m.group(1)):
            self.send_error(400, "bad name")
            return
        n = int(self.headers.get("Content-Length", 0))
        if n <= 0 or n > 20_000_000:
            self.send_error(413)
            return
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / m.group(1)).write_bytes(self.rfile.read(n))
        self.send_response(204)
        self.end_headers()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7310
    os.chdir(REPO)
    print(f"companion tools on http://127.0.0.1:{port}/aiws/companion/", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
