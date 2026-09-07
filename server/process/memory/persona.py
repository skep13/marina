"""What Marina is doing with her own time.

A friend exists between conversations. Without this she is a blank slate every
session — which is one of the things that makes a character feel like software.

The current thread is picked deterministically from the date, so it stays
consistent all day and has moved on by tomorrow. No LLM call, no state file to
corrupt, and it survives restarts for free.
"""
import hashlib
from datetime import date

from process.config import load_config

_config = load_config()
_persona = _config.get("persona") or {}

ENABLED = bool(_persona.get("enabled", True))

# Deliberately specific. "She makes videos" gives a small model nothing to work
# with; "the audio desyncs about four seconds in" gives it something to say.
DEFAULT_THREADS = [
    "You are four hours into a Jujutsu Kaisen edit and the audio desyncs about "
    "four seconds in every single time you export.",
    "You posted an edit last night that you were proud of and it has 12 views. "
    "You are pretending not to care.",
    "You have been trying to learn enough Rust to make a video about it and the "
    "borrow checker has personally humiliated you twice today.",
    "You are rewatching Mob Psycho instead of finishing the edit you promised "
    "people on Friday.",
    "A comment on your last coding video called your indentation 'a war crime' "
    "and you have thought about it every day since.",
    "You found a transition you love, used it in three edits in a row, and are "
    "now worried it has become your whole personality.",
    "Your last video did unexpectedly well and now you are stuck on what to "
    "post next, which is somehow worse than nobody watching.",
    "You have forty tabs open researching an anime retrospective you will "
    "almost certainly never make.",
]


def threads():
    custom = _persona.get("threads")
    return custom if isinstance(custom, list) and custom else DEFAULT_THREADS


def current_thread(when=None):
    """The thing on her mind today. Same all day, different tomorrow."""
    pool = threads()
    if not pool:
        return ""
    day = (when or date.today()).isoformat()
    seed = int(hashlib.sha256(day.encode()).hexdigest()[:8], 16)
    return pool[seed % len(pool)]


def as_prompt_block(when=None):
    if not ENABLED:
        return ""
    thread = current_thread(when)
    if not thread:
        return ""
    return (
        "\n\nWhat is going on in your life right now: "
        f"{thread} "
        "Bring it up if it fits. Do not force it into every reply."
    )
