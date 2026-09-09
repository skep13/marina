"""The small number of things she can actually do.

She had no agency at all: you could talk to her and she could talk back, and
that was the whole surface. These are deliberately few, local, and dull —
setting a timer, reading the clipboard you just copied to, opening a link,
writing something down. Nothing that spends money, deletes anything, or
reaches out of this machine.

Two constraints shaped the list. Small local models are mediocre at tool
selection, and every definition here is sent on every turn, so a long list
costs tokens and makes her worse at the thing she is mainly for, which is
talking. And a companion that quietly did large things would be alarming, so
the ceiling is deliberately low.

`open_url` is the only one that reaches outward, and it is restricted to
http(s) — no file://, no arbitrary schemes, nothing that runs a program.
"""
import json
import subprocess
import threading
import time
from urllib.parse import urlparse

from process.config import load_config
from process.memory import store as memory

_config = load_config()
_cfg = _config.get("tools") or {}

ENABLED = bool(_cfg.get("enabled", True))
ALLOW_CLIPBOARD = bool(_cfg.get("clipboard", True))
ALLOW_OPEN_URL = bool(_cfg.get("open_url", True))
ALLOW_TIMERS = bool(_cfg.get("timers", True))
CLIPBOARD_LIMIT = int(_cfg.get("clipboard_chars", 2000))

# Timers that have gone off and not yet been said out loud. The idle poll
# drains this, so a timer reaches you the same way an unprompted thought does.
_announcements = []
_lock = threading.Lock()


def pending_announcement():
    with _lock:
        return _announcements.pop(0) if _announcements else None


def _announce(text):
    with _lock:
        _announcements.append(text)


# ----------------------------------------------------------------------
#  The tools
# ----------------------------------------------------------------------

def set_timer(minutes, label=""):
    if not ALLOW_TIMERS:
        return "Timers are switched off."
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        return "That is not a number of minutes."
    if not 0 < minutes <= 24 * 60:
        return "Timers have to be between a moment and a day."

    what = (label or "").strip()

    def fire():
        time.sleep(minutes * 60)
        _announce(f"The timer you set{f' for {what}' if what else ''} just "
                  f"went off. Tell them, in your own words, in one sentence.")

    threading.Thread(target=fire, daemon=True).start()
    pretty = f"{int(minutes)} minutes" if minutes >= 1 else f"{int(minutes * 60)} seconds"
    print(f"[tool] timer set for {pretty}{f' ({what})' if what else ''}", flush=True)
    return f"Timer set for {pretty}{f' — {what}' if what else ''}."


def read_clipboard():
    if not ALLOW_CLIPBOARD:
        return "The clipboard is off limits."
    try:
        out = subprocess.run(["pbpaste"], capture_output=True, text=True, timeout=2)
    except Exception as e:                              # noqa: BLE001
        return f"Could not read the clipboard: {e}"
    text = (out.stdout or "").strip()
    if not text:
        return "The clipboard is empty."
    if len(text) > CLIPBOARD_LIMIT:
        text = text[:CLIPBOARD_LIMIT] + "… (truncated)"
    print(f"[tool] read clipboard ({len(text)} chars)", flush=True)
    return f"The clipboard contains:\n{text}"


def open_url(url):
    if not ALLOW_OPEN_URL:
        return "Opening links is switched off."
    url = (url or "").strip()
    parsed = urlparse(url)
    # http(s) only. Everything else — file://, custom schemes, anything that
    # would hand a path to another application — is refused outright.
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return "Only http and https links can be opened."
    try:
        subprocess.run(["open", url], timeout=3, check=False)
    except Exception as e:                              # noqa: BLE001
        return f"Could not open it: {e}"
    print(f"[tool] opened {url}", flush=True)
    return f"Opened {parsed.netloc}."


def remember(fact):
    fact = (fact or "").strip()
    if not fact:
        return "Nothing to remember."
    added = memory.add(fact, source="tool")
    print(f"[tool] remembered: {fact}", flush=True)
    return "Noted." if added else "Already knew that."


SPECS = [
    ("set_timer", set_timer, ALLOW_TIMERS, {
        "description": "Set a timer that will go off after a number of minutes. "
                       "Use when they ask to be reminded of something soon.",
        "parameters": {
            "type": "object",
            "properties": {
                "minutes": {"type": "number", "description": "How many minutes from now."},
                "label": {"type": "string", "description": "What the timer is for."},
            },
            "required": ["minutes"],
        }}),
    ("read_clipboard", read_clipboard, ALLOW_CLIPBOARD, {
        # Written at the failure mode rather than the feature. Described
        # neutrally, the model would answer "probably a typo" about an error
        # it had never seen — guessing reads as far worse than looking.
        "description": "Read what is on the clipboard. You cannot see it any "
                       "other way, so call this whenever they mention "
                       "something they copied or pasted, or refer to 'this' "
                       "error, link, message or snippet. Never guess at what "
                       "they copied.",
        "parameters": {"type": "object", "properties": {}},
        }),
    ("open_url", open_url, ALLOW_OPEN_URL, {
        "description": "Open a web link in their browser. Only http and https.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        }}),
    ("remember", remember, True, {
        "description": "Write down a durable fact about them, so it survives "
                       "this conversation. Only for things worth keeping.",
        "parameters": {
            "type": "object",
            "properties": {"fact": {"type": "string"}},
            "required": ["fact"],
        }}),
]

_HANDLERS = {name: fn for name, fn, on, _ in SPECS if on}


def definitions():
    """The OpenAI tool schema, or None when there is nothing to offer."""
    if not ENABLED:
        return None
    tools = [
        {"type": "function",
         "function": {"name": name, **spec}}
        for name, _fn, on, spec in SPECS if on
    ]
    return tools or None


def run(name, arguments):
    """Execute one tool call. Never raises — the model gets told what failed."""
    fn = _HANDLERS.get(name)
    if fn is None:
        return f"There is no tool called {name}."
    try:
        args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
    except json.JSONDecodeError:
        return "Those arguments were not valid JSON."
    if not isinstance(args, dict):
        return "Those arguments were not an object."
    try:
        return str(fn(**args))
    except TypeError as e:
        return f"Wrong arguments for {name}: {e}"
    except Exception as e:                              # noqa: BLE001
        return f"{name} failed: {type(e).__name__}: {e}"
