"""A mood she keeps.

Her prompt says her moods carry over from one message to the next, but with
nothing to hold a mood the model made one up each time, and "still a bit
put out" sometimes came out as plain meanness. This keeps two numbers:

  warmth   how she feels toward them right now  (-1 put out … +1 fond)
  energy   how lively she is                    (-1 flat   … +1 buzzing)

Each exchange nudges them, they drift back to her usual self over a couple
of hours, and warmth has a floor: she can be short with them, never cruel.
The mood goes on her newest message as a note only when it is far enough
from usual to be worth saying, and gives her face something to rest on
between expressions.
"""
import re
import threading
import time

from process import state
from process.config import setting

USUAL = {"warmth": 0.3, "energy": 0.1}
FLOOR = {"warmth": -0.45, "energy": -0.8}
HALF_LIFE = 2 * 3600.0     # seconds for a mood to fade halfway back to usual

_lock = threading.Lock()

_RUDE = re.compile(
    r"\b(shut up|stfu|you('?re| are) (so |really )?(useless|stupid|dumb|annoying|wrong|"
    r"boring|broken|an idiot)|stupid (bot|ai)|i hate you|go away|nobody asked|"
    r"that('?s| is| was) (so )?(stupid|dumb|wrong)|you suck|whatever)\b", re.I)
_SORRY = re.compile(r"\b(sorry|my bad|didn'?t mean (it|that)|i apologi[sz]e)\b", re.I)
_KIND = re.compile(
    r"\b(thank(s| you)|love (you|that|it|this)|you('?re| are) (the best|right|so right|"
    r"funny|great|amazing)|good (one|point|call)|nice one|well done|proud of you|"
    r"missed you|ha(ha)+|lol|lmao)\b", re.I)
_NEWS = re.compile(
    r"\b(guess what|you won'?t believe|we won|i won|i passed|i got (in|it|the)|"
    r"it works|it worked|finally|no way|omg|let'?s go+)\b|!{2,}", re.I)
_TIRED = re.compile(r"\b(tired|exhausted|knackered|sleepy|long day|can'?t be bothered|"
                    r"bored)\b", re.I)


def enabled():
    return bool(setting("mood", "enabled", True))


def _load():
    raw = state.get("mood")
    try:
        return {"warmth": float(raw["warmth"]), "energy": float(raw["energy"]),
                "at": float(raw["at"])}
    except (KeyError, TypeError, ValueError):
        return {**USUAL, "at": time.time()}


def _faded(state, now):
    """The state as it is now, drifted back toward her usual self."""
    keep = 0.5 ** (max(0.0, now - state["at"]) / HALF_LIFE)
    return {k: USUAL[k] + (state[k] - USUAL[k]) * keep for k in USUAL}


def current(now=None):
    with _lock:
        return _faded(_load(), now or time.time())


def _clamp(key, value):
    return max(FLOOR[key], min(1.0, value))


def feel(their_message, now=None):
    """Let what they just said move her mood. Returns the new mood."""
    text = their_message if isinstance(their_message, str) else ""
    text = text.replace("’", "'")
    now = now or time.time()
    with _lock:
        mood = _faded(_load(), now)
        if _RUDE.search(text):
            mood["warmth"] -= 0.35
        if _SORRY.search(text):
            mood["warmth"] += 0.3
        if _KIND.search(text):
            mood["warmth"] += 0.12
            mood["energy"] += 0.05
        if _NEWS.search(text):
            mood["energy"] += 0.25
        if _TIRED.search(text):
            mood["energy"] -= 0.1
        new = {k: _clamp(k, v) for k, v in mood.items()}
        state.put("mood", {**new, "at": now})
        return new


def describe(mood):
    """A few words for how she feels, or "" when she is her usual self."""
    w, e = mood["warmth"], mood["energy"]
    if w <= -0.2:
        return "still put out with them: shorter and drier than usual, not unkind"
    if w < 0.1:
        return "a little cool toward them after what was said; it will pass"
    if w >= 0.65 and e >= 0.4:
        return "in a properly good mood, a bit giddy"
    if w >= 0.65:
        return "feeling fond of them right now"
    if e >= 0.5:
        return "wide awake and a bit hyper"
    if e <= -0.35:
        return "low on energy, flat and slow to get going"
    return ""


def note(their_message=""):
    """Update her mood from their message and return the note for it, or ""."""
    if not enabled():
        return ""
    words = describe(feel(their_message))
    if not words:
        return ""
    return (f"\n\n(Note to you, not from them: your mood right now is {words}. Let it "
            "colour how you say things rather than announcing it.)")


def face(now=None):
    """{name, weight} for her face to rest on when a sentence has no feeling
    of its own, or None when she is her usual self."""
    if not enabled():
        return None
    mood = current(now)
    w, e = mood["warmth"], mood["energy"]
    if w <= -0.2:
        return {"name": "angry", "weight": 0.15}
    if w >= 0.65:
        return {"name": "happy", "weight": 0.2}
    if e <= -0.35:
        return {"name": "relaxed", "weight": 0.2}
    return None


def voice_speed(now=None):
    """How much faster or slower than usual she talks: a few percent either
    way with her energy, so a flat mood sounds flat."""
    if not enabled():
        return 1.0
    lift = current(now)["energy"] - USUAL["energy"]
    return 1.0 + max(-0.06, min(0.06, lift * 0.08))


def reset():
    with _lock:
        state.put("mood", {**USUAL, "at": time.time()})
