"""Knowing how long it has been.

Every saved message carries the time it was said. When they turn up after
a long gap, or for the first time that day, a note on her newest message
says so, so she can greet them like someone who noticed rather than
carrying on mid-thought from Tuesday.
"""
from datetime import datetime

NOTICE_HOURS = 6


def _at(message):
    try:
        return datetime.fromisoformat(message.get("at"))
    except (TypeError, ValueError, AttributeError):
        return None


def last_spoke(history):
    for m in reversed(history):
        when = _at(m) if isinstance(m, dict) else None
        if when:
            return when
    return None


def span(seconds):
    hours = seconds / 3600
    if hours < 20:
        return f"about {round(hours)} hours"
    days = max(1, round(hours / 24))
    if days == 1:
        return "about a day"
    return f"{days} days" if days < 14 else f"about {round(days / 7)} weeks"


def note(history, now=None):
    """The note for her newest message, or ""."""
    last = last_spoke(history)
    if last is None:
        return ""
    now = now or datetime.now(last.tzinfo)
    away = (now - last).total_seconds()
    new_day = last.date() != now.date() and now.hour >= 5
    if away < NOTICE_HOURS * 3600 and not (new_day and away >= 3 * 3600):
        return ""
    out = f"\n\n(Note to you, not from them: you two last talked {span(away)} ago"
    if new_day:
        out += ", and this is the first you've heard from them today"
    if away >= 3 * 86400:
        out += (". That is a while for you two; you noticed, and you can say so, "
                "lightly, without guilt-tripping them")
    return out + (". Pick up like someone who knows time has passed, not as if "
                  "the last message was a minute ago.)")
