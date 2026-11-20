#!/usr/bin/env python3
"""Decides when Marina's screen (marina-screen.service) runs, and lets the
desktop app change that (setup-lab3.sh screen).

She shows while a monitor is connected AND either it's within SCREEN_HOURS
(/etc/appliance/screen.conf, e.g. 17:00-22:00) or someone extended it. "Off"
turns her off until the current window ends. The monitor's power button can't
be seen from here (it keeps reporting connected), hence the hours.

Serves 127.0.0.1:7392 behind Caddy at /screen-power (trusted networks only):
  GET  /screen-power            status
  POST /screen-power/extend     {"minutes": 60}
  POST /screen-power/off
"""
import json
import re
import subprocess
import threading
import time
from datetime import datetime, timedelta
from glob import glob
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

CONF = Path("/etc/appliance/screen.conf")
STATE = Path("/var/lib/appliance/screen-power.json")
UNIT = "marina-screen"
lock = threading.Lock()


def hours():
    """(start, end) as minutes after midnight, or None for always."""
    try:
        m = re.search(r'^SCREEN_HOURS="?(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})"?', CONF.read_text(), re.M)
    except OSError:
        m = None
    if not m:
        return None
    h1, m1, h2, m2 = map(int, m.groups())
    return h1 * 60 + m1, h2 * 60 + m2


def window_end(now):
    """When today's window closes if we're inside it, else None."""
    span = hours()
    if span is None:
        return now + timedelta(days=3650)
    start, end = span
    mins = now.hour * 60 + now.minute
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if start <= end:
        return midnight + timedelta(minutes=end) if start <= mins < end else None
    # Overnight window, e.g. 20:00-02:00.
    if mins >= start:
        return midnight + timedelta(days=1, minutes=end)
    if mins < end:
        return midnight + timedelta(minutes=end)
    return None


def load():
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save(state):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state))


def connected():
    for f in glob("/sys/class/drm/card*-*/status"):
        try:
            if Path(f).read_text().strip() == "connected":
                return True
        except OSError:
            pass
    return False


def decide():
    now = datetime.now()
    t = now.timestamp()
    state = load()
    end = window_end(now)
    extended = state.get("extend_until", 0) > t
    off = state.get("off_until", 0) > t
    until = None
    if off:
        reason, want = "turned off", False
        until = state["off_until"]
    elif extended:
        reason, want = "extended", True
        until = state["extend_until"]
    elif end:
        reason, want = "scheduled", True
        until = end.timestamp()
    else:
        reason, want = "outside its hours", False
    mon = connected()
    if want and not mon:
        reason, want = "no monitor connected", False
    span = hours()
    return {
        "on": want,
        "reason": reason,
        "until": until,
        "until_text": datetime.fromtimestamp(until).strftime("%H:%M") if until else None,
        "hours": "always" if span is None else "%02d:%02d-%02d:%02d" % (span[0] // 60, span[0] % 60, span[1] // 60, span[1] % 60),
        "connected": mon,
    }


def active():
    return subprocess.run(["systemctl", "is-active", "-q", UNIT]).returncode == 0


def apply():
    with lock:
        want = decide()["on"]
        if want and not active():
            subprocess.run(["systemctl", "start", "--no-block", UNIT])
        elif not want and active():
            subprocess.run(["systemctl", "stop", "--no-block", UNIT])


def extend(minutes):
    minutes = max(5, min(int(minutes or 60), 12 * 60))
    with lock:
        now = datetime.now()
        state = load()
        base = now.timestamp()
        end = window_end(now)
        if state.get("extend_until", 0) > base:
            base = state["extend_until"]
        elif end and state.get("off_until", 0) <= now.timestamp():
            base = end.timestamp()
        save({"extend_until": base + minutes * 60, "off_until": 0})
    apply()


def turn_off():
    with lock:
        now = datetime.now()
        end = window_end(now)
        state = load()
        until = max(end.timestamp() if end else 0, state.get("extend_until", 0), now.timestamp() + 60)
        save({"extend_until": 0, "off_until": until})
    apply()


class Handler(BaseHTTPRequestHandler):
    def reply(self, body, code=200):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.rstrip("/") == "/screen-power":
            return self.reply({**decide(), "running": active()})
        self.reply({"error": "not found"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            body = {}
        path = self.path.rstrip("/")
        if path == "/screen-power/extend":
            extend(body.get("minutes", 60))
        elif path == "/screen-power/off":
            turn_off()
        else:
            return self.reply({"error": "not found"}, 404)
        time.sleep(0.3)
        self.reply({**decide(), "running": active()})

    def log_message(self, *args):
        pass


def loop():
    while True:
        try:
            apply()
        except Exception as e:  # keep deciding whatever happens
            print(f"[screen-ctl] {e}", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    threading.Thread(target=loop, daemon=True).start()
    ThreadingHTTPServer(("127.0.0.1", 7392), Handler).serve_forever()
