#!/usr/bin/env python3
# ====================================================================
#  Songbird pet - Mac side.
#
#  Every few seconds, works out what the Mac is up to (music playing,
#  which app is in front, whether anyone is at the keyboard, battery)
#  and publishes it, retained, to the pet's topic. Listens on the event
#  topic for the pet's button: play/pause, and a notification when the
#  focus timer ends.
#
#  Deps:  pip install paho-mqtt
#  Run:   python3 pet_feed.py            (Ctrl-C to stop)
#         python3 pet_feed.py --once     (print one reading and exit)
#  Config: feed_config.json next to this file (see feed_config.example.json)
# ====================================================================
import base64
import json
import os
import ssl
import subprocess
import sys
import time
import unicodedata
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
POLL_S = 3
HEARTBEAT_S = 30
AWAY_S = 5 * 60              # no keyboard/mouse for this long -> away

# Front app name (lowercase) -> what the pet does. First match wins; a
# key matches if it appears anywhere in the name. Extend in the config's
# "apps" map.
APPS = [
    ("zoom", "call"), ("facetime", "call"), ("teams", "call"), ("webex", "call"),
    ("code", "code"), ("cursor", "code"), ("xcode", "code"), ("terminal", "code"),
    ("iterm", "code"), ("warp", "code"), ("ghostty", "code"), ("pycharm", "code"),
    ("intellij", "code"), ("android studio", "code"), ("roblox studio", "code"),
    ("thonny", "code"), ("arduino", "code"), ("claude", "code"),
    ("steam", "game"), ("minecraft", "game"), ("roblox", "game"), ("epic", "game"),
    ("discord", "chat"), ("slack", "chat"), ("messages", "chat"), ("whatsapp", "chat"),
    ("telegram", "chat"), ("signal", "chat"), ("mail", "chat"),
    ("bambu", "make"), ("orca", "make"), ("prusa", "make"), ("cura", "make"),
    ("fusion", "make"), ("blender", "make"), ("figma", "make"), ("freecad", "make"),
    ("kicad", "make"), ("onshape", "make"),
    ("pages", "write"), ("word", "write"), ("notes", "write"), ("obsidian", "write"),
    ("notion", "write"), ("textedit", "write"),
    ("safari", "browse"), ("chrome", "browse"), ("firefox", "browse"), ("arc", "browse"),
    ("edge", "browse"), ("brave", "browse"), ("opera", "browse"),
]

_SPOTIFY = """
tell application "Spotify"
	if player state is stopped then return "stopped"
	set t to current track
	return (player state as string) & tab & (name of t) & tab & (artist of t) & tab & (player position as string) & tab & ((duration of t) / 1000 as string)
end tell
"""

_MUSIC = """
tell application "Music"
	if player state is stopped then return "stopped"
	set t to current track
	return (player state as string) & tab & (name of t) & tab & (artist of t) & tab & (player position as string) & tab & (duration of t as string)
end tell
"""

PLAYERS = (("Spotify", _SPOTIFY), ("Music", _MUSIC))


def _run(args, timeout=5):
    try:
        out = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _running(name):
    # pgrep first: asking a player that isn't open would launch it
    return subprocess.run(["pgrep", "-xq", name]).returncode == 0


def _num(s):
    try:
        return round(float(s.replace(",", ".")), 1)    # some locales say 12,5
    except ValueError:
        return 0.0


def _ascii(s):
    """The pet's font is plain ASCII: keep what it can draw (é -> e),
    drop the rest (Japanese, emoji)."""
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return " ".join(s.split())


# The song line is drawn here, in a real Japanese font, and sent as a 1-bit
# picture: the pet's own font is ASCII only and has no room for kanji.
ART_FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc"   # Hiragino Kaku Gothic
ART_SIZE = 12        # px; the most legible weight/size for kanji on the OLED
ART_H = 12           # rows sent (the yellow strip is 16, the LED bar sits under it)
ART_MAX_W = 640      # px, keeps the message well under the pet's buffer
_art_font = None


def render_line(text):
    """{'w','h','b'}: `text` as packed 1-bit rows (MSB first, rows padded to a
    byte, base64) - the layout Adafruit's drawBitmap takes. None if Pillow
    or the font isn't there; the pet then falls back to its ASCII line."""
    global _art_font
    try:
        from PIL import Image, ImageDraw, ImageFont
        if _art_font is None:
            _art_font = ImageFont.truetype(ART_FONT, ART_SIZE)
    except (ImportError, OSError):
        return None
    w = min(int(_art_font.getlength(text)) + 1, ART_MAX_W)
    if w <= 1:
        return None
    im = Image.new("1", (w, ART_H))
    d = ImageDraw.Draw(im)
    d.fontmode = "1"                       # no anti-aliasing on a 1-bit screen
    d.text((0, 0), text, font=_art_font, fill=1)
    return {"w": w, "h": ART_H, "b": base64.b64encode(im.tobytes()).decode()}


def now_playing():
    """{'player','playing','track','artist','pos','dur'} for the first music
    app that's open, or None. Open counts even with nothing playing: the
    pet shows the record whenever Spotify is up."""
    for name, script in PLAYERS:
        if not _running(name):
            continue
        raw = _run(["osascript", "-e", script])
        if not raw or raw == "stopped":
            return {"player": name, "playing": False, "track": name,
                    "artist": "", "pos": 0.0, "dur": 0.0}
        p = raw.split("\t")
        if len(p) < 5:
            continue
        line = p[1] + (" - " + p[2] if p[2] else "")
        track, artist = _ascii(p[1]), _ascii(p[2])
        if not track:                      # ASCII fallback when there's no picture
            track, artist = artist or name, ""
        return {"player": name, "playing": p[0] == "playing", "track": track,
                "artist": artist, "pos": _num(p[3]), "dur": _num(p[4]),
                "art": render_line(line)}
    return None


def frontmost_app():
    asn = _run(["lsappinfo", "front"], 1)
    raw = _run(["lsappinfo", "info", "-only", "name", asn], 1) if asn else ""
    return raw.rsplit("=", 1)[-1].strip().strip('"') if "=" in raw else ""


def idle_seconds():
    raw = _run(["ioreg", "-c", "IOHIDSystem", "-d", "4"], 2)
    for line in raw.splitlines():
        if '"HIDIdleTime"' in line:
            try:
                return int(line.rsplit("=", 1)[1]) / 1e9
            except ValueError:
                pass
    return 0.0


def battery():
    raw = _run(["pmset", "-g", "batt"], 1)
    for tok in raw.replace(";", " ").split():
        if tok.endswith("%"):
            try:
                return int(tok.rstrip("%")), "AC Power" in raw
            except ValueError:
                pass
    return None, None


def category(app, extra):
    name = app.lower()
    for key, mode in list(extra.items()) + APPS:
        if key.lower() in name:
            return mode
    return "idle"


def tz_offset():
    lt = time.localtime()
    return lt.tm_gmtoff


class Watcher:
    """Turns readings into the pet's state. Kept apart from the probes so
    it can be tested without a Mac."""

    def __init__(self, extra_apps=None):
        self.extra = extra_apps or {}
        self.active_since = time.time()

    def state(self, app, idle, music, batt, charging, now=None):
        now = now or time.time()
        away = idle >= AWAY_S
        if away:
            self.active_since = now
        st = {"app": app, "active": int(now - self.active_since), "tz": tz_offset()}
        if batt is not None:
            st["batt"], st["charging"] = batt, bool(charging)

        mode = category(app, self.extra)
        if away and not (music and music["playing"]):
            mode = "away"
        elif mode != "call" and music:
            mode = "music"
            st.update({k: music[k] for k in ("playing", "track", "artist", "pos", "dur")})
            if music.get("art"):
                st["art"] = music["art"]
        st["mode"] = mode
        return st


# --- MQTT -----------------------------------------------------------

def load_config():
    path = os.path.join(HERE, "feed_config.json")
    if not os.path.exists(path):
        sys.exit("No feed_config.json - copy feed_config.example.json and fill it in.")
    with open(path) as f:
        return json.load(f)


def notify(text):
    _run(["osascript", "-e",
          f'display notification "{text}" with title "Songbird" sound name "Glass"'])


def on_event(cfg, payload):
    try:
        ev = json.loads(payload)
    except ValueError:
        return
    kind = ev.get("event")
    if kind == "playpause":
        for name, _ in PLAYERS:
            if _running(name):
                _run(["osascript", "-e", f'tell application "{name}" to playpause'])
                print(f"[pet] play/pause in {name}", flush=True)
                break
    elif kind == "timer":
        if ev.get("phase") == "break":
            notify("Focus round done - take a break.")
        else:
            notify("Break's over - hold the pet's button to start the next round.")
        print(f"[pet] timer -> {ev.get('phase')}", flush=True)
    elif kind == "pat":
        print("[pet] she got a pat", flush=True)


def connect(cfg):
    import paho.mqtt.client as mqtt

    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"songbird-pet-feed-{uuid.uuid4().hex[:6]}")
    c.username_pw_set(cfg["user"], cfg["pass"])
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE          # self-signed broker, same as the token
    c.tls_set_context(ctx)
    topic, events = cfg.get("topic", "songbird/pet"), cfg.get("event_topic", "songbird/pet/event")
    # if the Mac drops off (sleep, crash) the pet hears it from the broker
    c.will_set(topic, json.dumps({"mode": "offline"}), qos=1, retain=True)

    def on_connect(client, _ud, _flags, rc, _props=None):
        print(f"[pet] connected to broker ({rc})", flush=True)
        client.subscribe(events)

    c.on_connect = on_connect
    c.on_message = lambda _c, _u, msg: on_event(cfg, msg.payload)
    c.reconnect_delay_set(2, 60)
    c.connect_async(cfg["broker"], int(cfg["port"]), 60)
    c.loop_start()
    return c, topic


def reading(w):
    batt, charging = battery()
    return w.state(frontmost_app(), idle_seconds(), now_playing(), batt, charging)


def main():
    if "--once" in sys.argv:
        print(json.dumps(reading(Watcher()), indent=2))
        return
    cfg = load_config()
    w = Watcher(cfg.get("apps"))
    client, topic = connect(cfg)
    last, last_sent = None, 0.0
    try:
        while True:
            st = reading(w)
            # pos/active tick every poll; only resend for those on the heartbeat
            key = {k: v for k, v in st.items() if k not in ("pos", "active")}
            if key != last or time.time() - last_sent > HEARTBEAT_S:
                client.publish(topic, json.dumps(st, separators=(",", ":")), qos=1, retain=True)
                if key != last:
                    print(f"[pet] {st['mode']:7} {st.get('track') or st['app']}", flush=True)
                last, last_sent = key, time.time()
            time.sleep(POLL_S)
    except KeyboardInterrupt:
        pass
    finally:
        client.publish(topic, json.dumps({"mode": "offline"}), qos=1, retain=True).wait_for_publish(3)
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
