"""Asking how it went.

When they mention something with a day attached ("my driving test is
tomorrow"), it is saved as an event (see process.memory.extract). Once the
day comes, a note on her newest message reminds her it happened, so she can
ask about it the way a friend would, without being asked to. After she has
had a couple of chances, or once they bring it up themselves, the event is
dropped; what they said about it lives on in the conversation.

A day she was only roughly given ("an interview next week") is stored with
a "~" after the date, and she asks whether it has happened yet rather than
how it went.

Like the clock, the note rides on the newest message and never goes into
the system prompt.
"""
import re
import threading
from datetime import date

from process import state
from process.config import setting
from process.memory import store

CHANCES = 2        # replies an event is put in front of her, per phase
FORGET_AFTER = 7   # days past, after which it's too late to ask

_lock = threading.Lock()

_DULL = set("the user has have their they them with for from that this will about going "
            "being into next week day today tomorrow".split())


def enabled():
    return (bool(setting("followups", "enabled", True))
            and bool(setting("llm", "recall", True)))


def _due(event):
    try:
        return date.fromisoformat(str(event.get("due"))[:10])
    except ValueError:
        return None


def _rough(event):
    return str(event.get("due", "")).endswith("~")


def _ago(days, due):
    if days == 1:
        return "yesterday"
    return f"on {due:%A}" if days < 7 else "a week ago"


def _shown():
    got = state.get("followups")
    return dict(got) if isinstance(got, dict) else {}


def _count(event, phase, add=0):
    key = f"{event['id']}|{phase}"
    with _lock:
        shown = _shown()
        if add:
            live = {e["id"] for e in store.events()}
            shown = {k: v for k, v in shown.items() if k.split("|")[0] in live}
            shown[key] = shown.get(key, 0) + add
            state.put("followups", shown)
        return shown.get(key, 0)


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]+", (text or "").lower())
            if len(w) > 3 and w not in _DULL}


def about(event, their_message):
    """Whether what they just said is about this event."""
    mine = _words(event["text"])
    return bool(mine) and len(mine & _words(their_message)) >= min(2, len(mine))


def pending(today=None):
    """(event, days since its day) for the one to bring up now, or None.
    Drops events that are too old to ask about."""
    today = today or date.today()
    best = None
    for e in store.events():
        due = _due(e)
        if due is None:
            continue
        days = (today - due).days
        if days > FORGET_AFTER:
            store.remove(e["id"])
            continue
        if days < 0:
            continue
        if _count(e, "day" if days == 0 else "after") >= CHANCES:
            continue
        if best is None or days > best[1]:
            best = (e, days)
    return best


def due_today(today=None):
    """Events whose day is today, for a text first thing."""
    today = today or date.today()
    return [e for e in store.events() if _due(e) == today and not _rough(e)]


def note(today=None, their_message=""):
    """The note for her newest message, or ""."""
    if not enabled():
        return ""
    today = today or date.today()
    found = pending(today)
    if not found:
        return ""
    event, days = found
    if days and their_message and about(event, their_message):
        # They are telling her how it went. Nothing to ask; it's done.
        store.remove(event["id"])
        return ""
    phase = "day" if days == 0 else "after"
    seen = _count(event, phase, add=1)
    if days and seen >= CHANCES:
        store.remove(event["id"])   # she has had her chances to ask
    what = event["text"].rstrip(".")
    tail = "It is their thing, not yours."
    if _rough(event):
        return ("\n\n(Note to you, not from them: something you remember them telling "
                f"you earlier: {what}. That was meant to be around now. If it fits, "
                f"ask whether it has happened yet, in your own words. {tail})")
    if days == 0:
        return ("\n\n(Note to you, not from them: something you remember them telling "
                f"you earlier: {what}. That is today. If it fits, bring it up the way "
                "a friend would: ask if it's happened yet or how they feel about it. "
                f"{tail} Don't force it in if they are in the middle of something else.)")
    return ("\n\n(Note to you, not from them: something you remember them telling you "
            f"earlier: {what}. That was {_ago(days, _due(event))}, and you haven't "
            "asked how it went. Ask, in your own words, unless they have already "
            f"told you or are in the middle of something else. {tail})")


def reset():
    state.put("followups", {})
