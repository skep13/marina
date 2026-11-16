#!/usr/bin/env python3
"""qwen-gate: an OpenAI-compatible front door that only serves Qwen3.8-27B.

Runs in ct110 next to llama-swap. Callers present one of the keys in
KEYS_FILE (one per line, '#' comments allowed; edit to add/revoke, no restart
needed). Every request is pinned to the `forge-deep` model, whatever model
name the caller sends, so these keys can never load Marina, Songbird or Forge.
The gate talks to llama-swap with its own internal key from UPSTREAM_KEY_FILE.
"""
import hmac
import http.client
import json
import os
import queue
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LISTEN = os.environ.get("GATE_LISTEN", "0.0.0.0")
PORT = int(os.environ.get("GATE_PORT", "8090"))
UPSTREAM = os.environ.get("GATE_UPSTREAM", "127.0.0.1:8080")
MODEL = os.environ.get("GATE_MODEL", "forge-deep")
PUBLIC_NAME = os.environ.get("GATE_PUBLIC_NAME", "qwen3.8-27b")
KEYS_FILE = os.environ.get("GATE_KEYS_FILE", "/etc/qwen-gate/keys")
UPSTREAM_KEY_FILE = os.environ.get("GATE_UPSTREAM_KEY_FILE", "/etc/qwen-gate/upstream.key")
MAX_BODY = 8 * 1024 * 1024
KEEPALIVE = 20  # seconds of upstream silence before sending filler
POST_PATHS = {"/v1/chat/completions", "/v1/completions"}


def load_keys():
    try:
        with open(KEYS_FILE) as f:
            return [l.split("#")[0].strip() for l in f if l.split("#")[0].strip()]
    except OSError:
        return []


def upstream_key():
    with open(UPSTREAM_KEY_FILE) as f:
        return f.read().strip()


class Gate(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "qwen-gate"

    def log_message(self, fmt, *args):  # journald gets method/path/status only
        print("%s %s" % (self.address_string(), fmt % args), flush=True)

    def send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def err(self, code, msg):
        self.send_json(code, {"error": {"message": msg, "code": code}})

    def authorized(self):
        auth = self.headers.get("Authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        if not token:
            token = self.headers.get("x-api-key", "").strip()
        if not token:
            return False
        ok = False
        for k in load_keys():  # check every key: no early exit timing hint
            ok |= hmac.compare_digest(token.encode(), k.encode())
        return ok

    def do_GET(self):
        if self.path in ("/health", "/"):
            return self.send_json(200, {"status": "ok"})
        if not self.authorized():
            return self.err(401, "invalid or missing API key")
        if self.path.rstrip("/") == "/v1/models":
            return self.send_json(200, {"object": "list", "data": [
                {"id": PUBLIC_NAME, "object": "model", "owned_by": "lab3"}]})
        self.err(404, "not found")

    def do_POST(self):
        if not self.authorized():
            return self.err(401, "invalid or missing API key")
        if self.path not in POST_PATHS:
            return self.err(404, "only /v1/chat/completions and /v1/completions are served")
        try:
            n = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            n = 0
        if n <= 0 or n > MAX_BODY:
            return self.err(400, "missing or oversized request body")
        try:
            req = json.loads(self.rfile.read(n))
            if not isinstance(req, dict):
                raise ValueError
        except ValueError:
            return self.err(400, "body must be a JSON object")
        req["model"] = MODEL  # pinned: callers can't pick another model
        stream = bool(req.get("stream"))
        body = json.dumps(req).encode()

        conn = http.client.HTTPConnection(UPSTREAM, timeout=900)
        result = queue.Queue()

        def call():
            try:
                conn.request("POST", self.path, body, {
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + upstream_key(),
                })
                result.put(conn.getresponse())
            except OSError as e:
                result.put(e)

        threading.Thread(target=call, daemon=True).start()
        try:
            # The Cloudflare tunnel drops a request that sends nothing for 100 s,
            # and a cold 27B load plus a long non-streamed answer takes longer.
            # If the model is slow to answer, commit to 200 and send filler the
            # client ignores: leading whitespace is valid JSON, ': ' lines are
            # SSE comments. A late upstream error still arrives as an error body.
            started = False
            while True:
                try:
                    resp = result.get(timeout=KEEPALIVE)
                    break
                except queue.Empty:
                    if not started:
                        self.send_response(200)
                        self.send_header("Content-Type", "text/event-stream" if stream else "application/json")
                        self.send_header("Cache-Control", "no-cache")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        self.close_connection = True
                        started = True
                    self.wfile.write(b": waiting for model\n\n" if stream else b" ")
                    self.wfile.flush()
            if isinstance(resp, Exception):
                raise resp
            if not started:
                self.send_response(resp.status)
                self.send_header("Content-Type", resp.getheader("Content-Type", "application/json"))
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self.close_connection = True
            while True:
                chunk = resp.read1(65536)
                if not chunk:
                    break
                if MODEL.encode() in chunk:  # don't leak the internal model id
                    chunk = chunk.replace(b'"%s"' % MODEL.encode(), b'"%s"' % PUBLIC_NAME.encode())
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except OSError as e:
            try:
                if started:  # headers already sent: finish with an error body
                    self.wfile.write(json.dumps({"error": {"message": "model backend unavailable", "code": 502}}).encode())
                else:
                    self.err(502, "model backend unavailable: %s" % e.__class__.__name__)
            except OSError:
                pass
        finally:
            conn.close()


if __name__ == "__main__":
    ThreadingHTTPServer((LISTEN, PORT), Gate).serve_forever()
