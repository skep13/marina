"""Calls: talking with her hands-free, like a phone call.

The app keeps the mic going in turns (you talk, she answers, it listens
again). While a call is on, every reply gets CALL_STYLE so she talks like
someone on the phone, and she answers the call with a greeting that isn't
saved as anything you said.
"""
import threading
import time

from process import config as cfg

CALL_STYLE = (
    "\n\nYou are on a voice call with them right now, hands-free: they hear "
    "your voice and nothing else. Talk the way people do on the phone: short, "
    "warm, spoken sentences, usually one to three. No lists, headings, "
    "markdown, links or emoji, and don't describe actions in asterisks. Ask "
    "something back now and then so it stays a conversation."
)

PICK_UP = (
    "\n\nThey just called you and you've picked up. Say hello the way you "
    "would answering a call from them: one or two sentences, and you can ask "
    "what's up. Don't repeat a greeting already in the conversation above."
)

_state = {"on": False, "since": 0.0}
_lock = threading.Lock()


def _setting(key, default):
    return cfg.setting("call", key, default)


def start():
    with _lock:
        if not _state["on"]:
            _state["on"] = True
            _state["since"] = time.time()
    print("[call] started", flush=True)
    return status()


def end():
    with _lock:
        seconds = time.time() - _state["since"] if _state["on"] else 0.0
        _state["on"] = False
    print(f"[call] ended after {seconds:.0f}s", flush=True)
    return {"ok": True, "on": False, "seconds": round(seconds)}


def active():
    return _state["on"]


def status():
    with _lock:
        on = _state["on"]
        seconds = time.time() - _state["since"] if on else 0.0
    return {"on": on, "seconds": round(seconds)}


def style():
    return "\n\n" + str(_setting("style", CALL_STYLE)).strip()


def pick_up():
    return style() + "\n\n" + str(_setting("pick_up", PICK_UP)).strip()


# How she writes when you're texting her and how she talks when you're
# talking to her: people text and call differently. A preset can replace
# either with its own words (style.text / style.voice), or turn one off with "".
TEXT_STYLE = (
    "\n\nThey are texting you right now and will read your reply, not hear "
    "it. Text like a real person on their phone: mostly lowercase, light "
    "punctuation, short. Often send two or three short messages instead of "
    "one, each on its own line. Slang like lol, ngl, omg is fine when it fits, "
    "and sometimes a single emoji. Never describe actions in asterisks."
)

VOICE_STYLE = (
    "\n\nThey are talking to you out loud and hear your voice. Talk like a "
    "person speaking, not writing: contractions, the odd um, like, or wait "
    "when you're thinking, and it's fine to correct yourself mid-sentence. "
    "Usually one to three spoken sentences. No lists, headings, markdown, "
    "links or emoji; to give several points, say them as speech."
)


def channel_style(channel):
    if channel not in ("text", "voice"):
        return ""
    default = TEXT_STYLE if channel == "text" else VOICE_STYLE
    words = str(cfg.setting("style", channel, default) or "").strip()
    return "\n\n" + words if words else ""


def extra_for(user_text, extra_system, channel=None):
    """The extra system text for one reply: the call style during a call,
    else how to write for the channel they're using (texting or talking).
    Unprompted replies (openers, timers) bring their own instruction and
    are left alone."""
    if user_text is None:
        return extra_system
    if _state["on"]:
        return (extra_system or "") + style()
    return ((extra_system or "") + channel_style(channel)) or None
