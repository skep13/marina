"""Push to their phone through ntfy, for when her app isn't open to hear her.

The iPhone app is sideloaded with a free Apple ID, which gets no push of its
own. ntfy's iPhone app does, so what she says unprompted (a reminder going
off, a follow-up, checking in) is published to a self-hosted ntfy on lab3
and arrives as a notification; tapping it opens her app.

Who is around decides whether she pushes:
  - the phone app tells the bridge when it comes to the front or leaves it
    (POST /presence), and its idle long poll says it is still there;
  - a desktop app holding /idle/listen open counts as someone to talk to.
With the phone in front, she just talks there. With only a desktop app open,
reminders still go to the phone as well, but her chatty openers don't. With
nobody around, the bridge says it itself and pushes it.

Set up by `push:` in character_config.yaml. The topic and the bridge's
publish token live in a separate file (`push.secret_file`, lines of
topic=... and token=...), so the config can be shared without them.
"""
import threading
import time
import urllib.request

from process.config import load_config, resolve_data

_cfg = load_config().get("push") or {}

ENABLED = bool(_cfg.get("enabled", False))
URL = str(_cfg.get("url") or "http://127.0.0.1:2586").rstrip("/")
CLICK = str(_cfg.get("click") or "marinaapp://open")
# How long a phone's idle poll keeps it counted as there, between polls.
PHONE_STALE = float(_cfg.get("phone_stale_seconds", 150))
DESK_STALE = float(_cfg.get("desk_stale_seconds", 20))
# Her chatty openers too, not just reminders and timers.
OPENERS = bool(_cfg.get("openers", True))


def _secret():
    out = {}
    path = _cfg.get("secret_file") or "ntfy.secret"
    try:
        for line in resolve_data(path).read_text().splitlines():
            key, _, value = line.partition("=")
            if key.strip() and value.strip():
                out[key.strip()] = value.strip()
    except OSError:
        pass
    return out


_SECRET = _secret()
TOPIC = str(_cfg.get("topic") or _SECRET.get("topic") or "")
TOKEN = str(_SECRET.get("token") or "")


def enabled():
    return ENABLED and bool(TOPIC)


# ---- who is around -----------------------------------------------------------

_lock = threading.Lock()
_phone = {"front": False, "seen": 0.0}
_desk = {"seen": 0.0, "streams": 0}


def phone_presence(front):
    with _lock:
        _phone["front"] = bool(front)
        _phone["seen"] = time.time()


def phone_polled():
    """Its idle poll is open. Only counts while it last said it was in front."""
    with _lock:
        _phone["seen"] = time.time()


def phone_here(now=None):
    now = now or time.time()
    with _lock:
        return _phone["front"] and now - _phone["seen"] < PHONE_STALE


def desk_stream(opened):
    with _lock:
        _desk["streams"] = max(0, _desk["streams"] + (1 if opened else -1))
        _desk["seen"] = time.time()


def desk_here(now=None):
    now = now or time.time()
    with _lock:
        return _desk["streams"] > 0 or now - _desk["seen"] < DESK_STALE


# ---- sending -----------------------------------------------------------------

def send(text, title="Marina", priority=None, tags=None):
    """Publish one notification. Returns True if ntfy took it."""
    text = (text or "").strip()
    if not enabled() or not text:
        return False
    req = urllib.request.Request(f"{URL}/{TOPIC}", data=text[:3800].encode("utf-8"),
                                 method="POST")
    req.add_header("Title", title)
    req.add_header("Click", CLICK)
    if priority:
        req.add_header("Priority", str(priority))
    if tags:
        req.add_header("Tags", ",".join(tags))
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            ok = 200 <= r.status < 300
    except Exception as e:
        print(f"[push] couldn't reach ntfy: {type(e).__name__}: {e}", flush=True)
        return False
    print(f"[push] sent: {text[:80]}", flush=True)
    return ok


def send_image(jpeg, text="", title="Marina", filename="screen.jpg"):
    """Publish a picture, with `text` as its message. ntfy keeps attachments
    on lab3 for a few hours, long enough to look at it from the phone."""
    if not enabled() or not jpeg:
        return False
    req = urllib.request.Request(f"{URL}/{TOPIC}", data=jpeg, method="PUT")
    req.add_header("Title", title)
    req.add_header("Filename", filename)
    req.add_header("Click", CLICK)
    if text:
        # Header values must be latin-1; anything else becomes "?".
        req.add_header("Message", text[:500].encode("latin-1", "replace").decode("latin-1"))
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            ok = 200 <= r.status < 300
    except Exception as e:
        print(f"[push] couldn't send the picture: {type(e).__name__}: {e}", flush=True)
        return False
    print(f"[push] sent a picture ({len(jpeg) // 1024} KB)", flush=True)
    return ok
