"""Her day has a shape. She is slow first thing, herself through the day,
and sleepy and softer late at night; now and then she was in the middle of
something when they messaged and says so.

A turn note, like her mood: nothing is saved, and the system prompt stays
the same. `rhythm.enabled: false` in the config turns it off; `busy_rate`
is how often she was busy (0 for never)."""
import random
from datetime import datetime

from process.config import setting

PARTS = [
    # (from hour, until hour, how she is)
    (5, 10, "It's early and you've not properly woken up yet: slower, a bit "
            "mumbly, short replies, maybe on your first drink of the day."),
    (23, 24, "It's late and you're getting sleepy: softer, a bit more honest "
             "than in the day, more easily distracted."),
    (0, 5, "It's the middle of the night and you should be asleep: drowsy, "
           "quiet, a little more open than usual, maybe teasing them for being "
           "up too."),
]


def part_of_day(hour):
    for start, end, how in PARTS:
        if start <= hour < end:
            return how
    return ""


def note(their_message="", now=None, roll=None):
    if not setting("rhythm", "enabled", True):
        return ""
    now = now or datetime.now()
    how = part_of_day(now.hour)
    busy = ""
    rate = float(setting("rhythm", "busy_rate", 0.08))
    if not how and their_message and (roll if roll is not None else random.random()) < rate:
        from process.memory import persona
        thread = persona.current_thread(now.date())
        busy = ("You were in the middle of something of your own when this came in"
                + (f" ({thread[0].lower() + thread[1:].rstrip('.')})" if thread else "")
                + ". You can say you were half distracted or just got back to them, "
                  "in a word or two, then answer properly.")
    text = " ".join(p for p in (how, busy) if p)
    return f"\n\n(Note to you, not from them: {text})" if text else ""
