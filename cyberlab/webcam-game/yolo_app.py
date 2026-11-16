import json
import os
import threading
import time
import urllib.request

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request, send_from_directory

STREAM = os.environ.get("CAM_STREAM", "http://127.0.0.1:8000/stream.mjpg")
CFG = "/root/yolo/yolov4-tiny.cfg"
WEIGHTS = "/root/yolo/yolov4-tiny.weights"
NAMES = "/root/yolo/coco.names"
INP = int(os.environ.get("YOLO_SIZE", "416"))
CONF = float(os.environ.get("YOLO_CONF", "0.4"))
USE_GPU = os.environ.get("YOLO_GPU", "0") == "1"
PERSON = 0
# Lower floor for the JSON feed so small held-up objects (phones, cups) still
# reach the game; the game applies its own per-class threshold.
GAME_CONF = float(os.environ.get("GAME_CONF", "0.25"))
GAME_HTML = os.environ.get("GAME_HTML", "/root/yolo/game.html")
SCORES = os.environ.get("GAME_SCORES", "/root/yolo/scores.json")
LOGOS = os.environ.get("LOGO_DIR", "/root/yolo/logos")

with open(NAMES) as f:
    LABELS = [l.strip() for l in f if l.strip()]

# DETECTOR=pose (default): YOLOv8n-pose, people + 17 COCO keypoints each.
# DETECTOR=yolo4: the original YOLOv4-tiny, 80 object classes, boxes only.
DETECTOR = os.environ.get("DETECTOR", "pose")
# 16:9 input matching the camera: no pixels wasted on letterbox padding.
# 512x288 nano: ~15 visible joints/person and 0.83 wrist confidence, against
# 13.7 / 0.76 for the old 320x320 square (which only saw a 320x180 picture).
POSE_W = int(os.environ.get("POSE_W", "512"))
POSE_H = int(os.environ.get("POSE_H", "288"))
POSE_MODEL = os.environ.get("POSE_MODEL", f"/root/yolo/pose-n-{POSE_H}x{POSE_W}.onnx")
# the container has 4 cores; more threads than that just thrash
cv2.setNumThreads(int(os.environ.get("CV_THREADS", "4")))
KP_CONF = 0.3
LEG_CONF = 0.65      # knees/ankles hidden behind desks still score ~0.6


def kp_visible(kp, box):
    """Which keypoints to draw: confident enough, and inside the person's own box."""
    x, y, w, h = box
    mx, my = w * .15, h * .06
    return [k[2] >= (LEG_CONF if i >= 13 else KP_CONF) and x - mx <= k[0] <= x + w + mx and y - my <= k[1] <= y + h + my
            for i, k in enumerate(kp)]
# COCO keypoint order: nose, eyes, ears, shoulders, elbows, wrists, hips, knees, ankles
SKELETON = [(5, 6), (5, 7), (7, 9), (6, 8), (8, 10), (5, 11), (6, 12), (11, 12),
            (11, 13), (13, 15), (12, 14), (14, 16), (0, 5), (0, 6)]

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

pose_net = None
if DETECTOR == "pose":
    pose_net = cv2.dnn.readNetFromONNX(POSE_MODEL)
    pose_net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    pose_net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)


def detect_pose(f):
    """People with keypoints: list of (conf, [x,y,w,h] px, (17,3) keypoints px)."""
    H, W = f.shape[:2]
    s = min(POSE_W / W, POSE_H / H)
    nw, nh = int(W * s), int(H * s)
    pad = np.full((POSE_H, POSE_W, 3), 114, np.uint8)
    pad[:nh, :nw] = cv2.resize(f, (nw, nh))
    pose_net.setInput(cv2.dnn.blobFromImage(pad, 1 / 255.0, (POSE_W, POSE_H), swapRB=True))
    o = pose_net.forward()[0].T                      # (N, 56): box(4) conf(1) kps(51)
    o = o[o[:, 4] > min(CONF, GAME_CONF)]
    if not len(o):
        return []
    boxes = [[float((r[0] - r[2] / 2) / s), float((r[1] - r[3] / 2) / s),
              float(r[2] / s), float(r[3] / s)] for r in o]
    keep = cv2.dnn.NMSBoxes(boxes, o[:, 4].tolist(), min(CONF, GAME_CONF), 0.45)
    out = []
    for i in np.array(keep).flatten():
        kp = o[i, 5:].reshape(17, 3).copy()
        kp[:, :2] /= s
        out.append((float(o[i, 4]), boxes[i], kp))
    return out

app = Flask(__name__)
frame_lock = threading.Lock()
latest = {"jpg": None}
out_lock = threading.Lock()
state = {"jpg": None, "raw": None, "dets": None}
score_lock = threading.Lock()
state_counts = {"people": 0, "fps": 0.0, "near": 0}
game_state = {"state": "", "players": 0, "at": 0.0}
NEAR_H = float(os.environ.get("NEAR_H", "0.42"))   # a box this tall (share of frame) = standing at the play spot


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
        H, W = f.shape[:2]
        dets = []
        n = 0
        near = 0
        if pose_net is not None:
            for conf, (x, y, w, h), kp in detect_pose(f):
                dets.append({"c": "person", "p": round(conf, 3),
                             "b": [round(x / W, 4), round(y / H, 4), round(w / W, 4), round(h / H, 4)],
                             "k": [[round(float(k[0]) / W, 4), round(float(k[1]) / H, 4), round(float(k[2]), 2)]
                                   for k in kp]})
                if conf < CONF:
                    continue
                n += 1
                if h / H >= NEAR_H:
                    near += 1
                vis = kp_visible(kp, (x, y, w, h))
                x, y, w, h = int(x), int(y), int(w), int(h)
                for a, b in SKELETON:
                    if vis[a] and vis[b]:
                        cv2.line(f, (int(kp[a, 0]), int(kp[a, 1])), (int(kp[b, 0]), int(kp[b, 1])),
                                 (255, 122, 30), 3, cv2.LINE_AA)
                for k, v in zip(kp, vis):
                    if v:
                        cv2.circle(f, (int(k[0]), int(k[1])), 5, (255, 220, 200), -1, cv2.LINE_AA)
            classes, confs, boxes = [], [], []
        else:
            classes, confs, boxes = model.detect(f, min(CONF, GAME_CONF), 0.4)
        for cid, conf, box in zip(np.array(classes).flatten(),
                                  np.array(confs).flatten(), boxes):
            x, y, w, h = (int(v) for v in box)
            dets.append({"c": LABELS[int(cid)], "p": round(float(conf), 3),
                         "b": [round(x / W, 4), round(y / H, 4),
                               round(w / W, 4), round(h / H, 4)]})
            if int(cid) != PERSON or conf < CONF:
                continue
            n += 1
            cv2.rectangle(f, (x, y), (x + w, y + h), (255, 122, 30), 3)
            txt = f"person {conf:.0%}"
            (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
            cv2.rectangle(f, (x, y - th - 10), (x + tw + 10, y), (255, 122, 30), -1)
            cv2.putText(f, txt, (x + 5, y - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (12, 14, 20), 2, cv2.LINE_AA)
        dt = time.time() - t0
        ema = dt if ema == 0 else ema * 0.9 + dt * 0.1
        fps = 1.0 / ema if ema else 0.0
        label = "person" if n == 1 else "people"
        # counts live in the page header now; keep the frame itself clean
        state_counts["people"] = n
        state_counts["near"] = near
        state_counts["fps"] = round(fps, 1)
        ok, buf = cv2.imencode(".jpg", f, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ok:
            with out_lock:
                state["jpg"] = buf.tobytes()
                # the untouched source frame and its detections, kept as one
                # pair so the game's video and boxes never drift apart
                state["raw"] = jpg
                state["seq"] = state.get("seq", 0) + 1
                state["at"] = time.time()
                state["dets"] = {"t": time.time(), "fps": round(fps, 1), "d": dets}


threading.Thread(target=capture, daemon=True).start()
threading.Thread(target=detector, daemon=True).start()


def mjpeg(key="jpg"):
    # send each processed frame once, and nothing while the camera is down, so
    # viewers see a stall (and reconnect) instead of a frozen picture
    last = -1
    while True:
        with out_lock:
            jpg, seq, at = state[key], state.get("seq", 0), state.get("at", 0)
        if jpg is None or seq == last or time.time() - at > 1.0:
            time.sleep(0.01)
            continue
        last = seq
        yield (b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
               + str(len(jpg)).encode() + b"\r\n\r\n" + jpg + b"\r\n")
        time.sleep(0.015)


@app.get("/stream.mjpg")
def stream():
    return Response(mjpeg(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/raw.mjpg")
def raw_stream():
    return Response(mjpeg("raw"), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.get("/logos/<path:name>")
def logos(name):
    r = send_from_directory(LOGOS, name)
    r.headers["Cache-Control"] = "max-age=86400"
    return r


@app.get("/status.json")
def status():
    age = time.time() - game_state["at"]
    return jsonify(dict(state_counts, game=game_state["state"] if age < 5 else "",
                        game_players=game_state["players"] if age < 5 else 0))


@app.post("/game_state")
def set_game_state():
    d = request.get_json(silent=True) or {}
    game_state.update(state=str(d.get("state", ""))[:12], players=int(d.get("players", 0) or 0), at=time.time())
    return jsonify(ok=True)


@app.get("/detections.json")
def detections():
    with out_lock:
        d = state["dets"]
    r = jsonify(d or {"t": 0, "fps": 0, "d": []})
    r.headers["Cache-Control"] = "no-store"
    return r


@app.get("/game")
def game():
    # read per request so the page can be tweaked without a restart
    with open(GAME_HTML, encoding="utf-8") as fh:
        r = Response(fh.read(), mimetype="text/html")
    r.headers["Cache-Control"] = "no-store"
    return r


def _load_scores():
    try:
        with open(SCORES) as fh:
            return json.load(fh)
    except Exception:
        return {"best": 0, "day": "", "today": 0, "recent": []}


@app.route("/scores", methods=["GET", "POST"])
def scores():
    with score_lock:
        s = _load_scores()
        day = time.strftime("%Y-%m-%d")
        if s.get("day") != day:
            s.update(day=day, today=0, top=[], games_today=0, all_today=[])
        if request.method == "POST":
            try:
                pts = max(0, min(100000, int((request.get_json(silent=True) or {}).get("score", 0))))
            except (TypeError, ValueError):
                pts = 0
            s["best"] = max(s.get("best", 0), pts)
            s["today"] = max(s.get("today", 0), pts)
            s["recent"] = ([pts] + s.get("recent", []))[:10]
            s["games"] = s.get("games", 0) + 1
            s["games_today"] = s.get("games_today", 0) + 1
            s["top"] = sorted(s.get("top", []) + [pts], reverse=True)[:5]
            # 1-based place among today's games (ties share the better place)
            s["rank"] = 1 + sum(1 for v in s.get("all_today", []) if v > pts)
            s["all_today"] = sorted(s.get("all_today", []) + [pts], reverse=True)[:500]
            tmp = SCORES + ".tmp"
            with open(tmp, "w") as fh:
                json.dump(s, fh)
            os.replace(tmp, SCORES)
        return jsonify(s)


@app.get("/")
def index():
    return PAGE, 200, {"Cache-Control": "no-store", "Content-Type": "text/html; charset=utf-8"}


PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>CyberLab Vision</title>
<style>
:root{--glass-border:rgba(22,80,200,.22);--ac:#1e7aff;--tx:rgba(200,220,255,.92);--dim:rgba(70,130,210,.6);
 --mono:'SF Mono','Fira Code','JetBrains Mono','Cascadia Code','Consolas',monospace}
*{margin:0;padding:0;box-sizing:border-box}
html,body{height:100%;background:#010508;color:var(--tx);font-family:var(--mono);overflow:hidden}
/* video fills the whole screen; header and footer float over it */
.video{position:fixed;inset:0}
.video canvas{width:100%;height:100%;display:block}
.vignette{position:fixed;inset:0;pointer-events:none;
 background:radial-gradient(ellipse 85% 75% at 50% 55%,transparent 55%,rgba(1,5,16,.35) 80%,rgba(1,5,16,.75) 100%)}
header{position:fixed;left:0;right:0;top:0;z-index:2;height:9vh;display:flex;align-items:center;gap:1.4vw;padding:0 2vw;
 background:rgba(1,5,16,.88);border-bottom:1px solid var(--glass-border);backdrop-filter:blur(6px)}
.logos{display:flex;align-items:center;gap:1.1vw;height:100%}
.logos img{height:5.8vh;width:auto;display:block;border-radius:.5vh}
.sep{width:1px;height:4.6vh;background:var(--glass-border);margin:0 .4vw}
h1{font-size:2.6vh;font-weight:700;color:#fff;letter-spacing:.14em;text-transform:uppercase}
h1 em{font-style:normal;color:var(--ac)}
.right{margin-left:auto;display:flex;align-items:center;gap:2.6vw}
.stat{text-align:right}
.stat b{display:block;font-size:4.2vh;line-height:1;color:#fff;font-variant-numeric:tabular-nums}
.stat span{font-size:1.6vh;letter-spacing:.22em;color:var(--dim);text-transform:uppercase}
.live{display:flex;align-items:center;gap:.6vw;padding:.7vh .9vw;border:1px solid rgba(255,35,35,.45);border-radius:4px;background:rgba(255,30,30,.1)}
.live i{width:1vh;height:1vh;border-radius:50%;background:#ff2222;box-shadow:0 0 8px #ff2222;animation:b 1.1s ease-in-out infinite}
.live span{font-size:1.6vh;color:#ff5555;letter-spacing:.18em;text-transform:uppercase}
@keyframes b{50%{opacity:.25}}
.cta{position:fixed;right:1.6vw;bottom:2vh;z-index:2;display:flex;align-items:center;gap:1.2vw;padding:1.4vh 1.6vw;
 background:rgba(1,5,16,.88);border:1px solid rgba(30,122,255,.55);border-radius:12px;box-shadow:0 0 3vh rgba(30,122,255,.25)}
.cta .go{font-size:3.4vh;color:var(--ac);animation:nudge 1.6s ease-in-out infinite}
.cta b{display:block;font-size:2.8vh;letter-spacing:.12em;color:#fff;text-transform:uppercase}
.cta b em{font-style:normal;color:var(--ac)}
.cta span{display:block;margin-top:.4vh;font-size:1.6vh;letter-spacing:.18em;color:var(--dim);text-transform:uppercase}
@keyframes nudge{50%{transform:translateX(.6vw)}}
.foot{position:fixed;left:1.6vw;bottom:2vh;z-index:2;padding:1vh 1.2vw;font-size:1.6vh;letter-spacing:.22em;
 text-transform:uppercase;color:var(--dim);background:rgba(1,5,16,.85);border:1px solid var(--glass-border);border-radius:10px}
</style></head><body>
<div class=video><canvas id=cam></canvas></div>
<div class=vignette></div>
<div class=stage>
 <header><div class=logos><img src="/logos/hackclub.svg" alt="Hack Club"><img src="/logos/coleg-gwent.svg" alt="Coleg Gwent"><img src="/logos/cybercollege-cymru.png" alt="Cyber College Cymru"></div><div class=sep></div><h1>CyberLab <em>Vision</em></h1>
  <div class=right>
   <div class=stat><b id=n>0</b><span>people</span></div>
   <div class=stat><b id=fps>0</b><span>fps</span></div>
   <div class=live><i></i><span>Live</span></div>
  </div></header>
 <div class=foot>AI pose tracking &middot; 17 points per person &middot; running live in this room</div>
 <div class=cta><div class=go>&#9654;</div><div><b>Step up &amp; play <em>Zone Grab</em></b><span id=best>stand in front of the camera</span></div></div>
</div>
<script>
// ---- self-healing MJPEG reader ---------------------------------------------
// Reads the multipart stream with fetch and paints the newest JPEG onto a
// canvas. If no frame arrives for 3 s (camera unplugged, server restart,
// network blip) the connection is dropped and reopened until frames flow again.
function mjpegCanvas(url, canvas, onFrame) {
  const ctx = canvas.getContext("2d");
  const st = {lastFrame: performance.now(), w: 0, h: 0};
  const find = (b, x, y, from) => { for (let i = from; i < b.length - 1; i++) if (b[i] === x && b[i + 1] === y) return i; return -1; };
  (async function loop() {
    for (;;) {
      const ctrl = new AbortController();
      const wd = setInterval(() => { if (performance.now() - st.lastFrame > 3000) ctrl.abort(); }, 1000);
      try {
        const rd = (await fetch(url + "?" + Date.now(), {cache: "no-store", signal: ctrl.signal})).body.getReader();
        let buf = new Uint8Array(0), busy = false;
        for (;;) {
          const {value, done} = await rd.read();
          if (done) break;
          const nb = new Uint8Array(buf.length + value.length); nb.set(buf); nb.set(value, buf.length); buf = nb;
          let jpg = null;
          for (;;) {
            const a = find(buf, 0xFF, 0xD8, 0); if (a < 0) { buf = new Uint8Array(0); break; }
            const b = find(buf, 0xFF, 0xD9, a + 2); if (b < 0) { buf = buf.slice(a); break; }
            jpg = buf.slice(a, b + 2); buf = buf.slice(b + 2);
          }
          if (buf.length > 4e6) buf = new Uint8Array(0);
          if (jpg && !busy) {                       // decode only the newest frame
            busy = true;
            createImageBitmap(new Blob([jpg], {type: "image/jpeg"})).then(bm => {
              const W = innerWidth, H = innerHeight;
              if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
              const ar = bm.width / bm.height, w = Math.max(W, H * ar), h = w / ar;   // cover
              ctx.drawImage(bm, (W - w) / 2, (H - h) / 2, w, h);
              st.w = bm.width; st.h = bm.height; st.lastFrame = performance.now();
              bm.close(); if (onFrame) onFrame(st);
            }).catch(() => {}).finally(() => { busy = false; });
          }
        }
      } catch (e) {}
      clearInterval(wd);
      await new Promise(r => setTimeout(r, 1000));
      st.lastFrame = performance.now();             // give the new connection a full 3 s
    }
  })();
  return st;
}
mjpegCanvas("/stream.mjpg", document.getElementById("cam"));
async function best(){try{const s=await(await fetch("/scores",{cache:"no-store"})).json();
 document.getElementById("best").textContent=s.today?("today's best: "+s.today+" \u00b7 can you beat it?"):"no games yet today \u00b7 be the first!"}catch(e){}}
best();setInterval(best,20000);
setInterval(async()=>{try{const s=await(await fetch("/status.json",{cache:"no-store"})).json();
 document.getElementById("n").textContent=s.people;document.getElementById("fps").textContent=Math.round(s.fps)}catch(e){}},500);
</script>
</body></html>"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8002")), threaded=True)
