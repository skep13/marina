import os
import threading
import time
import urllib.request

import cv2
import numpy as np
from flask import Flask, Response

STREAM = os.environ.get("CAM_STREAM", "http://127.0.0.1:8000/stream.mjpg")
CFG = "/root/yolo/yolov4-tiny.cfg"
WEIGHTS = "/root/yolo/yolov4-tiny.weights"
NAMES = "/root/yolo/coco.names"
INP = int(os.environ.get("YOLO_SIZE", "416"))
CONF = float(os.environ.get("YOLO_CONF", "0.4"))
USE_GPU = os.environ.get("YOLO_GPU", "0") == "1"
PERSON = 0

with open(NAMES) as f:
    LABELS = [l.strip() for l in f if l.strip()]

net = cv2.dnn.readNetFromDarknet(CFG, WEIGHTS)
net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
if USE_GPU:
    cv2.ocl.setUseOpenCL(True)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_OPENCL_FP16)
    try:
        print(f"[yolo] OpenCL haveOpenCL={cv2.ocl.haveOpenCL()} "
              f"useOpenCL={cv2.ocl.useOpenCL()} device={cv2.ocl.Device_getDefault().name()!r}",
              flush=True)
    except Exception as e:
        print(f"[yolo] OpenCL query failed: {e}", flush=True)
else:
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
model = cv2.dnn_DetectionModel(net)
model.setInputParams(size=(INP, INP), scale=1 / 255.0, swapRB=True)

app = Flask(__name__)
frame_lock = threading.Lock()
latest = {"jpg": None}
out_lock = threading.Lock()
state = {"jpg": None}


def capture():
    # Frame-dropping MJPEG reader: always keep only the newest JPEG, so the
    # detector never works through a backlog (keeps latency low while the
    # shared webcam-server stays the single camera owner).
    while True:
        try:
            r = urllib.request.urlopen(STREAM, timeout=5)
            buf = b""
            while True:
                chunk = r.read(65536)
                if not chunk:
                    break
                buf += chunk
                newest = None
                while True:
                    a = buf.find(b"\xff\xd8")
                    if a == -1:
                        break
                    b = buf.find(b"\xff\xd9", a + 2)
                    if b == -1:
                        break
                    newest = buf[a:b + 2]
                    buf = buf[b + 2:]
                if newest is not None:
                    with frame_lock:
                        latest["jpg"] = newest
                if len(buf) > 8_000_000:
                    buf = b""
        except Exception:
            time.sleep(0.5)


def detector():
    ema = 0.0
    while True:
        with frame_lock:
            jpg = latest["jpg"]
            latest["jpg"] = None
        f = None if jpg is None else cv2.imdecode(np.frombuffer(jpg, np.uint8), cv2.IMREAD_COLOR)
        if f is None:
            time.sleep(0.003)
            continue
        t0 = time.time()
        classes, confs, boxes = model.detect(f, CONF, 0.4)
        n = 0
        for cid, conf, box in zip(np.array(classes).flatten(),
                                  np.array(confs).flatten(), boxes):
            if int(cid) != PERSON:
                continue
            n += 1
            x, y, w, h = box
            cv2.rectangle(f, (x, y), (x + w, y + h), (110, 231, 110), 3)
            txt = f"person {conf:.0%}"
            (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.rectangle(f, (x, y - th - 10), (x + tw + 10, y), (110, 231, 110), -1)
            cv2.putText(f, txt, (x + 5, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (12, 14, 20), 2, cv2.LINE_AA)
        dt = time.time() - t0
        ema = dt if ema == 0 else ema * 0.9 + dt * 0.1
        fps = 1.0 / ema if ema else 0.0
        label = "person" if n == 1 else "people"
        cv2.putText(f, f"{fps:4.1f} FPS  |  {n} {label}", (14, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (110, 231, 255), 2, cv2.LINE_AA)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            with out_lock:
                state["jpg"] = buf.tobytes()


threading.Thread(target=capture, daemon=True).start()
threading.Thread(target=detector, daemon=True).start()


def mjpeg():
    while True:
        with out_lock:
            jpg = state["jpg"]
        if jpg is None:
            time.sleep(0.02)
            continue
        yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
               + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
        time.sleep(0.015)


@app.get("/stream.mjpg")
def stream():
    return Response(mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/")
def index():
    return PAGE


PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>CyberLab Vision</title>
<style>
:root{--bg:#070a12;--ac:#6ee7ff;--tx:#eaf2ff;--mut:#7f8db0}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:var(--bg);color:var(--tx);
 font-family:"SF Pro Display",Inter,system-ui,sans-serif;overflow:hidden}
.stage{height:100vh;display:flex;flex-direction:column}
header{display:flex;align-items:center;gap:14px;padding:18px 30px}
.dot{width:12px;height:12px;border-radius:50%;background:#ff4b5c;box-shadow:0 0 14px #ff4b5c;animation:b 1.3s infinite}
@keyframes b{50%{opacity:.25}}
header h1{font-size:22px;font-weight:600;letter-spacing:.16em;text-transform:uppercase}
header h1 em{font-style:normal;color:var(--ac)}
header .live{margin-left:auto;font-size:13px;letter-spacing:.2em;color:var(--mut);text-transform:uppercase}
.video{flex:1;display:flex;align-items:center;justify-content:center;min-height:0;padding:0 30px 30px}
.video img{max-width:100%;max-height:100%;border-radius:16px;
 box-shadow:0 20px 70px rgba(0,0,0,.6),0 0 0 1px rgba(110,231,255,.14)}
.foot{padding:0 30px 26px;font-size:14px;letter-spacing:.22em;text-transform:uppercase;color:var(--mut)}
</style></head><body>
<div class=stage>
 <header><span class=dot></span><h1>CyberLab <em>Vision</em></h1><span class=live>People detection &middot; live</span></header>
 <div class=video><img src="/stream.mjpg" alt="live detection"></div>
 <div class=foot>YOLOv4-tiny &middot; real-time on-device</div>
</div></body></html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8002")), threaded=True)
