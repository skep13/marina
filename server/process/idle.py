"""Decides when she says something without being asked. See `idle:` in
character_config.yaml for the limits."""
import difflib
import random
import re
import threading
import time
from datetime import datetime

from process.config import load_config, setting

_config = load_config()
_idle = _config.get("idle") or {}

MIN_GAP = float(_idle.get("min_gap_minutes", 25)) * 60
MAX_PER_HOUR = int(_idle.get("max_per_hour", 2))
PROBABILITY = float(_idle.get("probability", 0.5))
QUIET_FROM = int(_idle.get("quiet_from_hour", 23))
QUIET_UNTIL = int(_idle.get("quiet_until_hour", 9))
# Unanswered, she backs off: one opener, then another only after a long wait,
# then nothing until they reply. Without this she messaged every 25 minutes
# all day into silence, and each new one copied the pile above it.
MAX_UNANSWERED = int(_idle.get("max_unanswered", 2))
BACKOFF = float(_idle.get("unanswered_backoff_minutes", 120)) * 60

OPENER_INSTRUCTION = (
    "\n\nNothing has been said for a while and the silence is yours to break. "
    "Say one thing, unprompted: something on your mind, something you were "
    "reminded of, or a passing thought about them. One or two sentences. "
    "Do not offer help, do not ask what they are working on, and do not "
    "greet them as if they just arrived. It must not repeat anything already "
    "said above; the conversation is in front of you, so pick something else."
)

OWN_LIFE_RATE = float(_idle.get("own_life_rate", 0.5))


def opener_instruction(roll=None):
    """What to say when she breaks a silence. About half the time it is
    news from her own day, told like texting a friend, rather than a
    thought about them."""
    if (roll if roll is not None else random.random()) < OWN_LIFE_RATE:
        from process.memory import persona
        thread = persona.current_thread()
        if thread:
            return OPENER_INSTRUCTION + (
                " This time, tell them something from your own day, the way you'd "
                f"text a friend an update: {thread} Make it a reaction or a "
                "complaint or a tiny win, not a summary, and don't ask them to "
                "reply.")
    return OPENER_INSTRUCTION


_lock = threading.Lock()
_last_interaction = time.time()
_spoken_at = []
_muted = False


def enabled():
    """Read on every call: the presentation preset turns openers off."""
    return bool(setting("idle", "enabled", True))


def note_interaction():
    global _last_interaction
    with _lock:
        _last_interaction = time.time()


def muted():
    with _lock:
        return _muted


def set_muted(value):
    global _muted
    with _lock:
        _muted = bool(value)
    return _muted


def in_quiet_hours(now=None):
    hour = (now or datetime.now()).hour
    if QUIET_FROM == QUIET_UNTIL:
        return False
    if QUIET_FROM < QUIET_UNTIL:
        return QUIET_FROM <= hour < QUIET_UNTIL
    return hour >= QUIET_FROM or hour < QUIET_UNTIL


def note_spoken():
    now = time.time()
    with _lock:
        _spoken_at.append(now)
        _spoken_at[:] = [t for t in _spoken_at if now - t < 3600]
    note_interaction()


def _recent_count(now):
    return sum(1 for t in _spoken_at if now - t < 3600)


def status():
    now = time.time()
    with _lock:
        quiet_for = now - _last_interaction
        recent = _recent_count(now)
        is_muted = _muted
    return {
        "enabled": enabled(),
        "muted": is_muted,
        "quiet_for_seconds": round(quiet_for),
        "spoken_this_hour": recent,
        "max_per_hour": MAX_PER_HOUR,
        "in_quiet_hours": in_quiet_hours(),
    }


def may_notice(now=None):
    """Whether she may bring up something she noticed. The same limits as
    openers, except the gap since the last word: noticing is the reason."""
    if not enabled():
        return False
    now = now or time.time()
    with _lock:
        if _muted or (MAX_PER_HOUR and _recent_count(now) >= MAX_PER_HOUR):
            return False
    return not in_quiet_hours()


def unanswered(history):
    """How many times she has spoken up since they last said anything, not
    counting her answer to that, and when she last spoke."""
    trailing = 0
    last_at = None
    for m in reversed(history):
        if m.get("role") == "user":
            trailing -= 1          # her first message after theirs answered them
            break
        if m.get("role") == "assistant":
            trailing += 1
            if last_at is None:
                last_at = _at(m)
    return max(0, trailing), last_at


def _at(message):
    try:
        return datetime.fromisoformat(message.get("at")).timestamp()
    except (TypeError, ValueError, AttributeError):
        return None


def due(now=None, roll=None, history=None):
    """`history` is the conversation, or a function returning it; it is only
    read once the cheap checks have passed."""
    if not enabled():
        return False
    now = now or time.time()
    with _lock:
        if _muted:
            return False
        if now - _last_interaction < MIN_GAP:
            return False
        if MAX_PER_HOUR and _recent_count(now) >= MAX_PER_HOUR:
            return False
    if in_quiet_hours():
        return False
    if (roll if roll is not None else random.random()) >= PROBABILITY:
        return False
    if history is not None:
        n, last_at = unanswered(history() if callable(history) else history)
        if n >= MAX_UNANSWERED:
            return False
        if n and last_at and now - last_at < BACKOFF:
            return False
    return True


def _plain(text):
    text = re.sub(r"\*[^*\n]+\*", " ", text or "").lower()
    return " ".join(re.findall(r"[a-z0-9']+", text))


def too_similar(text, history, recent=12, ratio=0.6):
    """Whether a message she is about to send repeats one of her recent ones:
    the same opening words, or mostly the same text."""
    new = _plain(text)
    if not new:
        return True
    head = new.split()[:3]
    for m in reversed([m for m in history if m.get("role") == "assistant"][-recent:]):
        old = _plain(m.get("content") if isinstance(m.get("content"), str) else "")
        if not old:
            continue
        if len(head) == 3 and old.split()[:3] == head:
            return True
        if difflib.SequenceMatcher(None, new, old).ratio() >= ratio:
            return True
    return False


def avoid_note(history, recent=6):
    """Her latest messages, quoted, for a second try at saying something new."""
    said = [m.get("content") for m in history if m.get("role") == "assistant"
            and isinstance(m.get("content"), str)][-recent:]
    if not said:
        return ""
    lines = "\n".join(f'- "{s}"' for s in dict.fromkeys(_plain(s)[:120] for s in said))
    return ("\n\nYou have already said these, so do not reuse their words, "
            f"openings or ideas:\n{lines}\nSay something genuinely different, "
            "starting with a different word.")
