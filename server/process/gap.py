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


def _late(when):
    return 0 <= when.hour < 5


def moment(last, now):
    """A note about the time itself, for a short gap: they're up late, just
    back from their day, or back after an hour or so. Each fires once, on
    the first message it's true for, so she notices it the way a person
    would and then drops it."""
    away = (now - last).total_seconds()
    if _late(now) and (not _late(last) or away >= 2 * 3600):
        return ("\n\n(Note to you, not from them: it's past midnight for them, "
                f"{now:%H:%M}. You can notice they're up late, once and lightly, "
                "the way a friend would. Don't nag.)")
    if now.weekday() < 5 and 16 <= now.hour < 21 and away >= 4 * 3600 and last.hour < 16:
        return ("\n\n(Note to you, not from them: it's a weekday evening and you "
                "haven't heard from them since earlier today, so they're probably "
                "back from their day. You can ask how it went, if it fits.)")
    if away >= 3600:
        return (f"\n\n(Note to you, not from them: it's been {span(away)} since "
                "their last message. If it fits, you can notice they're back.)")
    return ""


def note(history, now=None):
    """The note for her newest message, or ""."""
    last = last_spoke(history)
    if last is None:
        return ""
    now = now or datetime.now(last.tzinfo)
    away = (now - last).total_seconds()
    new_day = last.date() != now.date() and now.hour >= 5
    if away < NOTICE_HOURS * 3600 and not (new_day and away >= 3 * 3600):
        return moment(last, now)
    out = f"\n\n(Note to you, not from them: you two last talked {span(away)} ago"
    if new_day:
        out += ", and this is the first you've heard from them today"
    if away >= 3 * 86400:
        out += (". That is a while for you two; you noticed, and you can say so, "
                "lightly, without guilt-tripping them")
    return out + (". Pick up like someone who knows time has passed, not as if "
                  "the last message was a minute ago.)")
