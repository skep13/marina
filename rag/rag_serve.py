#!/usr/bin/env python3
"""Tiny stdlib HTTP wrapper over ``rag query`` so the appliance serves retrieval
at ``/rag`` (behind Caddy, reachable as http://ai.local/rag). Run it as a
systemd service on lab3:

    ExecStart=/opt/rag/.venv/bin/python /opt/rag/rag_serve.py   (HOME=/root)

GET /rag?q=<question>&k=6&domain=<d>&source=<s>  ->  the query() JSON.
The lab3 embedding key comes from ~/.marina/agent-keys.env via the rag CLI.
"""
import json, subprocess, urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

RAG = "/opt/rag/bin/rag"


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path.rstrip("/") != "/rag":
            self.send_response(404); self.end_headers(); return
        q = urllib.parse.parse_qs(u.query)
        query = (q.get("q") or [""])[0]
        try:
            k = str(max(1, min(20, int((q.get("k") or ["6"])[0]))))
        except ValueError:
            k = "6"
        args = [RAG, "query", query, "--k", k, "--compact"]
        if q.get("domain"):
            args += ["--domain", q["domain"][0]]
        if q.get("source"):
            args += ["--source", q["source"][0]]
        try:
            r = subprocess.run(args, capture_output=True, text=True, timeout=60, cwd="/opt/rag")
            body = r.stdout.encode() if r.returncode == 0 else json.dumps({"error": r.stderr[-300:]}).encode()
            code = 200 if r.returncode == 0 else 500
        except Exception as e:
            body = json.dumps({"error": str(e)}).encode(); code = 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers(); self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 7391), H).serve_forever()
