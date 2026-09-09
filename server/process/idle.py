"""When she says something without being asked.

She already has a life — `memory/persona.py` gives her a thread she is stuck on
for the day — and until now the only way to hear about it was to speak first.
A friend who never opens their mouth unprompted is a search box with a face.

The whole risk here is being annoying, so the defaults are timid and every
limit is a config key:

  - `min_gap_minutes`  nothing until the room has been quiet this long
  - `max_per_hour`     a hard ceiling regardless of anything else
  - `probability`      not every eligible moment is taken, so it is not a
                       metronome you can set your watch by
  - `quiet_hours`      no opening the conversation overnight
  - muting             one switch, honoured immediately, remembered

Nothing here fires while she is mid-reply or the user is mid-sentence; the
bridge only asks whether it is time when it has nothing else to do.
"""
import random
import threading
import time
from datetime import datetime

from process.config import load_config

_config = load_config()
_idle = _config.get("idle") or {}

ENABLED = bool(_idle.get("enabled", True))
MIN_GAP = float(_idle.get("min_gap_minutes", 25)) * 60
MAX_PER_HOUR = int(_idle.get("max_per_hour", 2))
PROBABILITY = float(_idle.get("probability", 0.5))
# Local hours during which she stays quiet. Inclusive start, exclusive end,
# and it wraps around midnight.
QUIET_FROM = int(_idle.get("quiet_from_hour", 23))
QUIET_UNTIL = int(_idle.get("quiet_until_hour", 9))

# What she is being asked to do. Deliberately not "be helpful": the failure
# mode for an unprompted line is "is there anything I can help you with?",
# which is the single least friend-like sentence available.
OPENER_INSTRUCTION = (
    "\n\nNothing has been said for a while and the silence is yours to break. "
    "Say one thing, unprompted — something on your mind, something you were "
    "reminded of, or a passing thought about them. One or two sentences. "
    "Do not offer help, do not ask what they are working on, and do not "
    "greet them as if they just arrived. It must not repeat anything already "
    "said above; the conversation is in front of you, so pick something else."
)

_lock = threading.Lock()
_last_interaction = time.time()
_spoken_at = []          # timestamps of recent openers, for the hourly cap
_muted = False


def note_interaction():
    """Called whenever anything passes between them, in either direction."""
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
    return hour >= QUIET_FROM or hour < QUIET_UNTIL     # wraps midnight


def note_spoken():
    now = time.time()
    with _lock:
        _spoken_at.append(now)
        # Only the last hour matters to the cap, so the list stays tiny.
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
        "enabled": ENABLED,
        "muted": is_muted,
        "quiet_for_seconds": round(quiet_for),
        "spoken_this_hour": recent,
        "max_per_hour": MAX_PER_HOUR,
        "in_quiet_hours": in_quiet_hours(),
    }


def due(now=None, roll=None):
    """Is this a moment to say something? Checked often; true rarely."""
    if not ENABLED:
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
    # The last gate is a coin flip, so that being quiet for exactly
    # `min_gap_minutes` is not a reliable way to summon her.
    return (roll if roll is not None else random.random()) < PROBABILITY
