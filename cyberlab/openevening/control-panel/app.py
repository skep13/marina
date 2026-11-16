import json
import logging
import os
import subprocess
import threading
import time
import urllib3
import requests
from flask import Flask, jsonify, render_template, request

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.json")

DEFAULT_SERVICES = {
    "buttonsite": {
        "label": "ButtonSite",
        "url": "http://raspberrypi.local:5000",
        "description": "Exploit trigger & SSH executor",
    },
    "guacamole": {
        "label": "Guacamole Wrapper",
        "url": "http://raspberrypi.local:5050",
        "description": "Remote desktop display blanker",
    },
    "hat_drawing": {
        "label": "HAT Drawing Pi",
        "url": "http://raspberrypi.local:5000",
        "description": "Pixel art canvas (Drawing Pi)",
    },
    "hat_receiver": {
        "label": "HAT Receiver Pi",
        "url": "http://raspberrypi.local:5001",
        "description": "Sense HAT LED matrix controller",
    },
    "hat_receiver_2": {
        "label": "HAT Receiver Pi 2",
        "url": "http://raspberrypi.local:5002",
        "description": "Second Sense HAT LED matrix controller",
    },
}

DEFAULT_PROXMOX = {
    "url": "https://192.168.x.x:8006",
    "node": "pve",
    "vmid": "",
    "snapshot": "clean",
    "token_id": "root@pam!mytoken",
    "token_secret": "",
    "blank_duration": 120,
    "blank_message": "RESETTING — PLEASE WAIT",
    "post_reset_url": "http://192.168.0.245",
}


def load_config():
    saved = {}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                saved = json.load(f)
        except Exception:
            pass

    config = {k: dict(v) for k, v in DEFAULT_SERVICES.items()}
    for k, v in saved.items():
        if k in config:
            config[k].update(v)

    prox = dict(DEFAULT_PROXMOX)
    prox.update(saved.get("proxmox", {}))
    config["proxmox"] = prox

    return config


def save_config(config):
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


def _check_online(url, timeout=3):
    try:
        r = requests.get(url, timeout=timeout, verify=False)
        return r.status_code < 500
    except Exception:
        return False


def _post(url, data=None, timeout=10):
    try:
        r = requests.post(url, json=data, timeout=timeout)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _proxmox_headers(prox):
    return {"Authorization": f"PVEAPIToken={prox['token_id']}={prox['token_secret']}"}


def _reset_kali_and_button(buttonsite_url):
    """Reset the Kali terminal and re-arm the button — the part of a reset
    that lives entirely on the button Pi / Kali Pi, no Proxmox or Guacamole
    involved. Shared by the full reset and the soft reset."""
    results = {}

    try:
        r = requests.post(f"{buttonsite_url}/api/terminal/reset", timeout=15)
        results["terminal"] = r.json()
    except Exception as e:
        results["terminal"] = {"ok": False, "error": str(e)}

    try:
        r = requests.post(f"{buttonsite_url}/api/arm", timeout=10)
        results["button"] = r.json()
    except Exception as e:
        results["button"] = {"ok": False, "error": str(e)}

    return results


@app.get("/")
def dashboard():
    return render_template("dashboard.html", config=load_config())


@app.get("/config")
def config_page():
    return render_template("config.html", config=load_config())


@app.get("/api/config")
def get_config():
    return jsonify(load_config())


@app.post("/api/config")
def post_config():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400
    save_config(data)
    return jsonify({"ok": True})


@app.get("/api/status")
def api_status():
    config = load_config()
    status = {
        key: _check_online(device["url"])
        for key, device in config.items()
        if key != "proxmox"
    }
    prox = config["proxmox"]
    if prox.get("url") and prox["url"] != DEFAULT_PROXMOX["url"]:
        status["proxmox"] = _check_online(prox["url"])
    return jsonify(status)


@app.post("/api/exploit")
def api_exploit():
    config = load_config()
    url = config["buttonsite"]["url"]
    data = request.get_json() or {}
    return jsonify(_post(f"{url}/press", data, timeout=15))


@app.post("/api/blank")
def api_blank():
    config = load_config()
    url = config["guacamole"]["url"]
    data = request.get_json() or {}
    return jsonify(_post(f"{url}/api/blank", data))


@app.post("/api/unblank")
def api_unblank():
    config = load_config()
    url = config["guacamole"]["url"]
    return jsonify(_post(f"{url}/api/unblank"))


@app.post("/api/attackmap")
def api_attackmap():
    config = load_config()
    url = config["guacamole"]["url"]
    data = request.get_json() or {}
    return jsonify(_post(f"{url}/api/attackmap", data))


@app.get("/api/attackmap")
def api_attackmap_status():
    config = load_config()
    url = config["guacamole"]["url"]
    try:
        r = requests.get(f"{url}/api/attackmap", timeout=5)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.get("/api/idle")
def api_idle_status():
    url = load_config()["guacamole"]["url"]
    try:
        return jsonify(requests.get(f"{url}/api/idle", timeout=5).json())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/idle")
def api_idle_set():
    url = load_config()["guacamole"]["url"]
    return jsonify(_post(f"{url}/api/idle", request.get_json() or {}))


@app.post("/api/hat/clear")
def api_hat_clear():
    config = load_config()
    url = config["hat_drawing"]["url"]
    return jsonify(_post(f"{url}/api/clear"))


@app.post("/api/hat/fill")
def api_hat_fill():
    config = load_config()
    url = config["hat_drawing"]["url"]
    data = request.get_json() or {}
    return jsonify(_post(f"{url}/api/fill", data))


@app.post("/api/hat/alert")
def api_hat_alert():
    """Flash the second HAT receiver red violently for alerts."""
    config = load_config()
    url = config["hat_receiver_2"]["url"]
    log.info("HAT alert: sending to %s", url)

    red_grid = [[255, 0, 0] for _ in range(64)]

    try:
        r = requests.post(f"{url}/api/display", json={"grid": red_grid}, timeout=5)
        r.raise_for_status()
    except Exception as e:
        log.error("HAT alert: first display call failed: %s", e)
        return jsonify({"ok": False, "error": f"Could not reach HAT receiver 2 at {url}: {e}"}), 500

    # First call succeeded — fire the remaining flashes best-effort
    time.sleep(0.25)
    for _ in range(4):
        _post(f"{url}/api/clear", timeout=5)
        time.sleep(0.25)
        _post(f"{url}/api/display", {"grid": red_grid}, timeout=5)
        time.sleep(0.25)
    _post(f"{url}/api/clear", timeout=5)

    log.info("HAT alert: done")
    return jsonify({"ok": True, "message": f"Alert sent to {url}"})


@app.post("/api/reset")
def api_reset():
    config = load_config()
    prox = config["proxmox"]
    guac_url = config["guacamole"]["url"]
    results = {}

    # Step 1 — blank the screen so audience sees a hold screen during restore
    blank_result = _post(
        f"{guac_url}/api/blank",
        {"duration": int(prox.get("blank_duration", 120)), "message": prox.get("blank_message", "RESETTING — PLEASE WAIT")},
    )
    results["blank"] = blank_result

    # Step 2 — Proxmox snapshot rollback
    pve_url = prox.get("url", "").rstrip("/")
    node = prox.get("node", "pve")
    vmid = prox.get("vmid", "")
    snapshot = prox.get("snapshot", "")
    token_id = prox.get("token_id", "")
    token_secret = prox.get("token_secret", "")

    missing = [k for k, v in {"url": pve_url, "vmid": vmid, "snapshot": snapshot, "token_id": token_id, "token_secret": token_secret}.items() if not v]
    if missing:
        results["proxmox"] = {"ok": False, "error": f"Proxmox not configured: missing {', '.join(missing)}"}
        return jsonify({"ok": False, "results": results})

    endpoint = f"{pve_url}/api2/json/nodes/{node}/qemu/{vmid}/snapshot/{snapshot}/rollback"
    try:
        r = requests.post(endpoint, headers=_proxmox_headers(prox), verify=False, timeout=20)
        body = r.json()
        upid = body.get("data", "")
        results["proxmox"] = {"ok": bool(upid), "upid": upid}
        if not upid:
            results["proxmox"]["error"] = body.get("errors") or r.text
    except Exception as e:
        results["proxmox"] = {"ok": False, "error": str(e)}

    # Step 3 — reset the Kali terminal and re-arm the button immediately once
    # the snapshot is sent, no need to wait for the VM restore to finish
    buttonsite_url = config["buttonsite"]["url"].rstrip("/")
    results.update(_reset_kali_and_button(buttonsite_url))

    ok = all(r.get("ok") for r in results.values())
    return jsonify({"ok": ok, "results": results})


@app.post("/api/reset/soft")
def api_reset_soft():
    """Just the Kali Pi terminal reset + button re-arm — no screen blank,
    no Proxmox snapshot rollback. For between-demo cleanup when the victim
    VM itself doesn't need restoring."""
    config = load_config()
    buttonsite_url = config["buttonsite"]["url"].rstrip("/")
    results = _reset_kali_and_button(buttonsite_url)
    ok = all(r.get("ok") for r in results.values())
    return jsonify({"ok": ok, "results": results})


@app.get("/api/reset/task/<path:upid>")
def api_reset_task(upid):
    config = load_config()
    prox = config["proxmox"]
    pve_url = prox.get("url", "").rstrip("/")
    node = prox.get("node", "pve")
    endpoint = f"{pve_url}/api2/json/nodes/{node}/tasks/{upid}/status"
    try:
        r = requests.get(endpoint, headers=_proxmox_headers(prox), verify=False, timeout=10)
        return jsonify(r.json())
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/reset/post")
def api_reset_post():
    """Called by the client after Proxmox confirms the task is done."""
    config = load_config()
    base = config["proxmox"].get("post_reset_url", "").rstrip("/")

    if not base:
        return jsonify({"ok": False, "error": "post_reset_url not configured"})

    results = {}

    try:
        r = requests.post(f"{base}/api/refresh", timeout=10)
        results["refresh"] = {"ok": r.status_code < 500}
    except Exception as e:
        results["refresh"] = {"ok": False, "error": str(e)}

    time.sleep(2)

    try:
        r = requests.post(f"{base}/api/unblank", timeout=10)
        results["unblank"] = {"ok": r.status_code < 500}
    except Exception as e:
        results["unblank"] = {"ok": False, "error": str(e)}

    core_ok = results.get("refresh", {}).get("ok", False) and results.get("unblank", {}).get("ok", False)
    return jsonify({"ok": core_ok, "results": results})


SELF_VMID = 107
GUEST_ACTIONS = {"start", "shutdown", "reboot", "stop"}


@app.get("/api/guests")
def api_guests():
    prox = load_config()["proxmox"]
    url = f"{prox['url'].rstrip('/')}/api2/json/cluster/resources?type=vm"
    try:
        r = requests.get(url, headers=_proxmox_headers(prox), verify=False, timeout=10)
        rows = r.json()["data"]
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    keep = ("vmid", "name", "type", "status", "cpu", "mem", "maxmem", "uptime")
    guests = [
        {k: g.get(k) for k in keep}
        for g in rows
        if g.get("node") == prox["node"] and not g.get("template")
    ]
    guests.sort(key=lambda g: g["vmid"])
    return jsonify({"ok": True, "self": SELF_VMID, "demo": str(prox.get("vmid")), "guests": guests})


@app.post("/api/guests/<kind>/<int:vmid>/<action>")
def api_guest_action(kind, vmid, action):
    if kind not in ("lxc", "qemu") or action not in GUEST_ACTIONS:
        return jsonify({"ok": False, "error": "bad request"}), 400
    if vmid == SELF_VMID and action != "start":
        return jsonify({"ok": False, "error": "this is the control panel itself"}), 400

    prox = load_config()["proxmox"]
    url = f"{prox['url'].rstrip('/')}/api2/json/nodes/{prox['node']}/{kind}/{vmid}/status/{action}"
    try:
        r = requests.post(url, headers=_proxmox_headers(prox), verify=False, timeout=20)
        body = r.json()
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    upid = body.get("data")
    if not upid:
        return jsonify({"ok": False, "error": str(body.get("errors") or r.text)}), 502
    log.info("guest %s/%s %s", kind, vmid, action)
    return jsonify({"ok": True, "upid": upid})


SSH_KEY = "/root/.ssh/id_ed25519"
SVC_GROUPS = {
    "kiosk": {"host": "192.168.1.113", "kind": "systemd", "names": ["kiosk"]},
    "webcam": {"host": "192.168.1.110", "kind": "systemd", "names": ["webcam-server", "yolo-web"]},
    "guac": {"host": "192.168.1.108", "kind": "docker", "names": ["blanker", "guacamole", "guacd", "guac-nginx", "guac-db"]},
}


def _ssh(host, cmd, timeout=10):
    r = subprocess.run(
        ["ssh", "-i", SSH_KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", f"root@{host}", cmd],
        capture_output=True, text=True, timeout=timeout,
    )
    return r.returncode, (r.stdout + r.stderr).strip()


def _group_status(g):
    names = g["names"]
    try:
        if g["kind"] == "systemd":
            _, out = _ssh(g["host"], "systemctl is-active " + " ".join(names))
            states = out.split("\n")
            up = [s.strip() == "active" for s in states[: len(names)]]
        else:
            code, out = _ssh(g["host"], "docker ps --format '{{.Names}}'")
            if code:
                return {"error": out or "ssh failed"}
            running = set(out.split())
            up = [n in running for n in names]
    except Exception as e:
        return {"error": str(e)}
    return {"units": [{"name": n, "up": u} for n, u in zip(names, up)]}


@app.get("/containers")
def containers_page():
    return render_template("containers.html", config=load_config())


@app.get("/api/svc")
def api_svc():
    return jsonify({k: _group_status(g) for k, g in SVC_GROUPS.items()})


@app.post("/api/svc/<group>/<name>/restart")
def api_svc_restart(group, name):
    g = SVC_GROUPS.get(group)
    if not g or name not in g["names"]:
        return jsonify({"ok": False, "error": "unknown service"}), 400
    verb = "systemctl restart" if g["kind"] == "systemd" else "docker restart"
    try:
        code, out = _ssh(g["host"], f"{verb} {name}", timeout=60)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    log.info("svc %s/%s restart -> %s", group, name, code)
    return jsonify({"ok": code == 0, "error": out if code else None})


reload_stamp = 0


@app.post("/api/kiosk/reload")
def api_kiosk_reload():
    global reload_stamp
    reload_stamp = int(time.time())
    return jsonify({"ok": True})


DISPLAY_FILE = os.path.join(os.path.dirname(__file__), "display_mode.txt")
DISPLAY_URLS = {
    "person": "http://192.168.1.110:8002/",
    "game": "http://192.168.1.110:8002/game",
    "attackmap": "http://192.168.1.108/static/attackmap.html",
}


def get_display_mode():
    try:
        m = open(DISPLAY_FILE).read().strip()
        return m if m in DISPLAY_URLS else "person"
    except Exception:
        return "person"


@app.get("/api/display")
def api_display_get():
    return jsonify(mode=get_display_mode(), urls=DISPLAY_URLS, reload=reload_stamp)


@app.post("/api/display")
def api_display_set():
    mode = (request.get_json() or {}).get("mode")
    if mode not in DISPLAY_URLS:
        return jsonify({"ok": False, "error": "unknown mode"}), 400
    with open(DISPLAY_FILE, "w") as f:
        f.write(mode)
    return jsonify({"ok": True, "mode": mode})


@app.get("/display")
def display_page():
    return DISPLAY_PAGE


DISPLAY_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Display</title>
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}
iframe{border:0;width:100vw;height:100vh;display:block}</style></head><body>
<iframe id=f src="about:blank" allow="autoplay"></iframe>
<script>
const U={person:"http://192.168.1.110:8002/",game:"http://192.168.1.110:8002/game",attackmap:"http://192.168.1.108/static/attackmap.html"};
let cur="",rl=null;
async function tick(){
 try{const d=await (await fetch("/api/display",{cache:"no-store"})).json();
  const f=document.getElementById("f");
  if(rl!==null&&d.reload!==rl){f.src="about:blank";setTimeout(()=>{f.src=U[d.mode]||U.person;},200);}
  rl=d.reload;
  if(d.mode!==cur){cur=d.mode;f.src=U[d.mode]||U.person;}
 }catch(e){}
}
tick();setInterval(tick,1500);
</script></body></html>"""


@app.get("/howto")
def howto_page():
    return open(os.path.join(os.path.dirname(__file__), "howto.html")).read()


DISPLAY2_FILE = os.path.join(os.path.dirname(__file__), "display2_mode.txt")
DISPLAY2_URLS = {
    "howto": "/howto",
    "person": "http://192.168.1.110:8002/",
    "game": "http://192.168.1.110:8002/game",
    "attackmap": "http://192.168.1.108/static/attackmap.html",
}
reload_stamp2 = 0


def get_display2_mode():
    try:
        m = open(DISPLAY2_FILE).read().strip()
        return m if m in DISPLAY2_URLS else "howto"
    except Exception:
        return "howto"


@app.get("/api/display2")
def api_display2_get():
    return jsonify(mode=get_display2_mode(), urls=DISPLAY2_URLS, reload=reload_stamp2)


@app.post("/api/display2")
def api_display2_set():
    mode = (request.get_json() or {}).get("mode")
    if mode not in DISPLAY2_URLS:
        return jsonify({"ok": False, "error": "unknown mode"}), 400
    with open(DISPLAY2_FILE, "w") as f:
        f.write(mode)
    return jsonify({"ok": True, "mode": mode})


@app.post("/api/kiosk2/reload")
def api_kiosk2_reload():
    global reload_stamp2
    reload_stamp2 = int(time.time())
    return jsonify({"ok": True})


@app.get("/display2")
def display2_page():
    return DISPLAY2_PAGE


DISPLAY2_PAGE = """<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Info</title>
<style>html,body{margin:0;height:100%;background:#000;overflow:hidden}
iframe{border:0;width:100vw;height:100vh;display:block}</style></head><body>
<iframe id=f src="about:blank" allow="autoplay"></iframe>
<script>
const U={howto:"/howto",person:"http://192.168.1.110:8002/",game:"http://192.168.1.110:8002/game",attackmap:"http://192.168.1.108/static/attackmap.html"};
let cur="",rl=null;
async function tick(){
 try{const d=await (await fetch("/api/display2",{cache:"no-store"})).json();
  const f=document.getElementById("f");
  if(rl!==null&&d.reload!==rl){f.src="about:blank";setTimeout(()=>{f.src=U[d.mode]||U.howto;},200);}
  rl=d.reload;
  if(d.mode!==cur){cur=d.mode;f.src=U[d.mode]||U.howto;}
 }catch(e){}
}
tick();setInterval(tick,1500);
</script></body></html>"""



# ── live view of the big screen ──────────────────────────────────────────────
# A background thread grabs the kiosk's Wayland screen with grim over one
# shared ssh connection, but only while a control panel is actually watching
# (someone asked for a frame in the last 10 s). Every viewer gets the same
# latest frame, so ten open phones still cost one capture loop.
SCREEN_HOST = "192.168.1.113"
SCREEN_CMD = ("su kiosk -s /bin/sh -c "
              "'XDG_RUNTIME_DIR=/run/cage WAYLAND_DISPLAY=wayland-0 grim -s 0.4 -l 1 -'")
SCREEN_IDLE_S = 10
_screen = {"png": None, "at": 0.0, "wanted": 0.0, "err": None, "thread": None}
_screen_lock = threading.Lock()


def _screen_loop():
    while True:
        if time.time() - _screen["wanted"] > SCREEN_IDLE_S:
            time.sleep(0.3)
            continue
        try:
            r = subprocess.run(
                ["ssh", "-i", SSH_KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=4",
                 "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/ssh-screen-%r@%h",
                 "-o", "ControlPersist=60", f"root@{SCREEN_HOST}", SCREEN_CMD],
                capture_output=True, timeout=8,
            )
            if r.returncode == 0 and r.stdout.startswith(b"\x89PNG"):
                _screen.update(png=r.stdout, at=time.time(), err=None)
                time.sleep(0.15)
            else:
                _screen["err"] = r.stderr.decode(errors="replace").strip()[-200:] or "capture failed"
                time.sleep(2)
        except Exception as e:
            _screen["err"] = str(e)
            time.sleep(2)


@app.get("/api/screen.png")
def api_screen():
    _screen["wanted"] = time.time()
    with _screen_lock:
        if _screen["thread"] is None:
            _screen["thread"] = threading.Thread(target=_screen_loop, daemon=True)
            _screen["thread"].start()
    png = _screen["png"]
    age = time.time() - _screen["at"]
    if not png or age > 15:
        return jsonify(error=_screen["err"] or "starting"), 503
    return png, 200, {"Content-Type": "image/png", "Cache-Control": "no-store",
                      "X-Screen-Age": f"{age:.1f}"}


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5555, debug=False)
