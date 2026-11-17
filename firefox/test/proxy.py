#!/usr/bin/env python3
"""Test-only: forwards 127.0.0.1:4341/v1/* to lab3, adding the browser key
from ~/.config/lab3/browser.key, so the harness page never holds the key."""
import http.client, http.server, os, sys
from pathlib import Path
LAB3 = ("192.168.1.15", 8080)
KEY = (Path.home() / ".config/lab3/browser.key").read_text().strip()

class H(http.server.BaseHTTPRequestHandler):
    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization, content-type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    def do_OPTIONS(self):
        self.send_response(204); self.cors(); self.end_headers()
    def forward(self, method):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) or None
        c = http.client.HTTPConnection(*LAB3, timeout=600)
        c.request(method, self.path, body, {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"})
        r = c.getresponse()
        self.send_response(r.status); self.cors()
        self.send_header("Content-Type", r.getheader("Content-Type", "application/json"))
        self.end_headers()
        while chunk := r.read1(4096):
            self.wfile.write(chunk); self.wfile.flush()
    def do_GET(self): self.forward("GET")
    def do_POST(self): self.forward("POST")
    def log_message(self, *a): pass

http.server.ThreadingHTTPServer(("127.0.0.1", 4341), H).serve_forever()
