import os
import threading
import time

import cv2
from flask import Flask, Response, jsonify

DEVICE = int(os.environ.get("CAM_DEVICE", "0"))
WIDTH = int(os.environ.get("CAM_WIDTH", "1280"))
HEIGHT = int(os.environ.get("CAM_HEIGHT", "720"))
FPS = int(os.environ.get("CAM_FPS", "30"))
PORT = int(os.environ.get("CAM_PORT", "8000"))

app = Flask(__name__)


class Camera:
    def __init__(self, src):
        self.src = src
        self.cap = None
        self.frame = None
        self.last_ok = 0.0
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()
        threading.Thread(target=self._watchdog, daemon=True).start()

    def _watchdog(self):
        # When the USB camera drops out, cap.read() can hang for a long time.
        # If frames stop for 6 s after we had them, exit and let systemd
        # restart us with a fresh device handle.
        while True:
            time.sleep(1)
            if self.last_ok and time.time() - self.last_ok > 6:
                print("camera stalled; restarting", flush=True)
                os._exit(1)

    def _open(self):
        cap = cv2.VideoCapture(self.src, cv2.CAP_V4L2)
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, FPS)
        return cap

    def _loop(self):
        while True:
            if self.cap is None or not self.cap.isOpened():
                if self.cap:
                    self.cap.release()
                self.cap = self._open()
                if not self.cap.isOpened():
                    time.sleep(2)
                    continue
            ok, frame = self.cap.read()
            if not ok:
                self.cap.release()
                self.cap = None
                time.sleep(0.5)
                continue
            with self.lock:
                self.frame = frame
                self.last_ok = time.time()

    def jpeg(self):
        with self.lock:
            # never serve a stale frame: a frozen picture looks like a live one
            stale = time.time() - self.last_ok > 1.0
            f = None if self.frame is None or stale else self.frame.copy()
        if f is None:
            return None
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 80])
        return buf.tobytes() if ok else None


cam = Camera(DEVICE)


def mjpeg():
    interval = 1.0 / FPS
    while True:
        jpg = cam.jpeg()
        if jpg is None:
            time.sleep(0.1)
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
               + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
        time.sleep(interval)


@app.get("/stream.mjpg")
def stream():
    return Response(mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/snapshot.jpg")
def snapshot():
    jpg = cam.jpeg()
    if jpg is None:
        return "no frame yet", 503
    return Response(jpg, mimetype="image/jpeg")


@app.get("/health")
def health():
    age = round(time.time() - cam.last_ok, 2) if cam.last_ok else None
    return jsonify(ok=cam.frame is not None, age_s=age, device=DEVICE)


@app.get("/")
def index():
    return (
        "<!doctype html><title>webcam-server</title>"
        "<style>body{margin:0;background:#111;color:#bbb;font-family:sans-serif;"
        "display:flex;flex-direction:column;align-items:center}"
        "img{max-width:100%;height:auto}h1{font-weight:400;font-size:.95rem;padding:.5rem}"
        "code{color:#6cf}</style>"
        "<h1>webcam-server &middot; <code>/stream.mjpg</code> &middot; "
        "<code>/snapshot.jpg</code> &middot; <code>/health</code></h1>"
        '<img src="/stream.mjpg">'
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, threaded=True)
