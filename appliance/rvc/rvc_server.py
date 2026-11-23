"""Her RVC voice on lab3: turns Kokoro's speech into the voice model's.

POST /convert with a WAV body, get the converted WAV back. One conversion at
a time, on the CPU so it never competes with the model on the GPU. Runs from
its own Python 3.10 env (/opt/rvc/.venv), since RVC's dependencies don't
install on newer Pythons. See README.md.

    RVC_MODEL=/opt/rvc/models/marin/Marin.pth RVC_INDEX=... python rvc_server.py
"""
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch

torch.set_num_threads(int(os.environ.get("RVC_THREADS", "8")))

from rvc_python.infer import RVCInference  # noqa: E402

MODEL = os.environ.get("RVC_MODEL", "/opt/rvc/models/marin/Marin.pth")
INDEX = os.environ.get("RVC_INDEX", "")
PITCH = int(os.environ.get("RVC_PITCH", "0"))
INDEX_RATE = float(os.environ.get("RVC_INDEX_RATE", "0.5"))
PORT = int(os.environ.get("RVC_PORT", "8790"))
MAX_BODY = 20 << 20

rvc = RVCInference(device="cpu:0")
rvc.load_model(MODEL, index_path=INDEX)
rvc.set_params(f0method="rmvpe", f0up_key=PITCH, index_rate=INDEX_RATE, protect=0.33)
lock = threading.Lock()


def convert(wav):
    with tempfile.TemporaryDirectory() as d:
        src, dst = os.path.join(d, "in.wav"), os.path.join(d, "out.wav")
        with open(src, "wb") as f:
            f.write(wav)
        with lock:
            rvc.infer_file(src, dst)
        with open(dst, "rb") as f:
            return f.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body, kind):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, b'{"ok": true}', "application/json")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if self.path != "/convert":
            return self._send(404, b"not found", "text/plain")
        n = int(self.headers.get("Content-Length") or 0)
        if not 0 < n <= MAX_BODY:
            return self._send(400, b"send a WAV body", "text/plain")
        t = time.time()
        try:
            out = convert(self.rfile.read(n))
        except Exception as e:
            print("convert failed:", e, flush=True)
            return self._send(500, str(e).encode(), "text/plain")
        print(f"converted {n >> 10} KB in {time.time() - t:.2f}s", flush=True)
        self._send(200, out, "audio/wav")


if __name__ == "__main__":
    convert(open(os.path.join(os.path.dirname(__file__), "warmup.wav"), "rb").read()) \
        if os.path.exists(os.path.join(os.path.dirname(__file__), "warmup.wav")) else None
    print(f"RVC voice ready on 127.0.0.1:{PORT} ({os.path.basename(MODEL)})", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
