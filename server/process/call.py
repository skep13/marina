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


def extra_for(user_text, extra_system):
    """The extra system text for one reply: the call style is added to what
    someone says during a call. Unprompted replies (openers, timers) bring
    their own instruction and are left alone."""
    if not _state["on"] or user_text is None:
        return extra_system
    return (extra_system or "") + style()
