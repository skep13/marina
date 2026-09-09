"""What is going on around her, without being asked.

A companion that has to be told the time is not in the room with you. None of
this needs a tool call or a round trip — it is a handful of cheap reads folded
into the system prompt, so she simply knows.

What it deliberately does not do: read window titles, read what is on screen,
or look at documents. macOS hands out the frontmost application's *name*
without any permission prompt, and that is the whole of it — "they are in
Firefox", never which page. Screen content stays behind the explicit
screenshot in `vision/look.py`, which only ever runs when you ask it to.

Every signal is individually switchable in `context:`, and a failed read is
simply left out rather than raised.
"""
import subprocess
from datetime import datetime

from process.config import load_config

_config = load_config()
_ctx = _config.get("context") or {}

ENABLED = bool(_ctx.get("enabled", True))
SHOW_TIME = bool(_ctx.get("time", True))
SHOW_APP = bool(_ctx.get("frontmost_app", True))
SHOW_BATTERY = bool(_ctx.get("battery", True))

# Anything slower than this is not worth having on every single turn.
TIMEOUT = 0.6


def _run(args):
    try:
        out = subprocess.run(args, capture_output=True, text=True,
                             timeout=TIMEOUT)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:                                   # noqa: BLE001
        return ""


def time_of_day(now=None):
    now = now or datetime.now()
    hour = now.hour
    part = ("the middle of the night" if hour < 5 else
            "early morning" if hour < 8 else
            "morning" if hour < 12 else
            "afternoon" if hour < 17 else
            "evening" if hour < 22 else
            "late evening")
    return f"{now.strftime('%A')} {part}, {now.strftime('%H:%M')}"


def frontmost_app():
    """The app in front, by name only.

    `lsappinfo` answers this without the accessibility permission that reading
    a window title would need — which is the reason it is used here rather
    than the AppleScript route.
    """
    asn = _run(["lsappinfo", "front"])
    if not asn:
        return ""
    raw = _run(["lsappinfo", "info", "-only", "name", asn])
    # Comes back as: "LSDisplayName"="Firefox"
    if "=" not in raw:
        return ""
    return raw.rsplit("=", 1)[-1].strip().strip('"')


def battery():
    raw = _run(["pmset", "-g", "batt"])
    if not raw:
        return ""
    charging = "AC Power" in raw
    percent = ""
    for token in raw.replace(";", " ").split():
        if token.endswith("%"):
            percent = token.rstrip("%;")
            break
    if not percent:
        return ""
    level = int(percent)
    # Only worth a sentence when it is actually notable.
    if charging:
        return "on charge" if level < 95 else ""
    if level <= 15:
        return f"on battery, down to {level}% and not charging"
    if level <= 35:
        return f"on battery, {level}% left"
    return ""


def as_prompt_block():
    """A line of ambient context, or nothing at all."""
    if not ENABLED:
        return ""

    bits = []
    if SHOW_TIME:
        bits.append(f"it is {time_of_day()}")
    if SHOW_APP:
        app = frontmost_app()
        if app:
            bits.append(f"they are in {app}")
    if SHOW_BATTERY:
        state = battery()
        if state:
            bits.append(f"the laptop is {state}")

    if not bits:
        return ""
    return (
        "\n\nAround you right now: " + "; ".join(bits) + ". "
        "Use this only if it is actually relevant — do not read it back to "
        "them or comment on it for its own sake."
    )
