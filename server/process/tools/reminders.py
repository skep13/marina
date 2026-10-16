"""Reminders for a set time, kept in reminders.json so they survive a restart.

Timers are for "in ten minutes"; these are for "Thursday at 3". When one is
due it goes out the same way a timer does, through the announcement queue,
so it reaches whichever of the app or Telegram is listening. One the bridge
was off for is still delivered when it comes back, as a late one.
"""
import json
import threading
import time
import uuid
from datetime import datetime, timedelta

from process.config import resolve_data

FILE = resolve_data("reminders.json")
CHECK_SECONDS = 15
MAX_PENDING = 50
LATE_AFTER = timedelta(minutes=5)

_lock = threading.Lock()
_watcher = None


def _load():
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(items):
    tmp = FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, indent=2)
    tmp.replace(FILE)


def parse_when(when, now=None):
    """A local date and time from what the model wrote, or None.

    It is told the current date and time, so it can turn "Thursday at 3" into
    "2026-10-22 15:00" itself; this only has to read that."""
    text = " ".join((when or "").replace("T", " ").split())
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %I:%M %p",
                "%Y-%m-%d %I%p", "%Y-%m-%d"):
        try:
            at = datetime.strptime(text.upper() if "%p" in fmt else text, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d":
            at = at.replace(hour=9)
        return at
    return None


def _pretty(at, now=None):
    now = now or datetime.now()
    day = ("today" if at.date() == now.date()
           else "tomorrow" if at.date() == (now + timedelta(days=1)).date()
           else at.strftime("%A %-d %B"))
    return f"{day} at {at.strftime('%-I:%M %p').lower()}"


def set_reminder(when, what):
    what = " ".join((what or "").split())
    if not what:
        return "What should the reminder say?"
    at = parse_when(when)
    if at is None:
        return ("Couldn't read that time. Give it as YYYY-MM-DD HH:MM in their "
                "local time, worked out from the current date.")
    now = datetime.now()
    if at <= now:
        return f"{_pretty(at, now)} has already passed."
    if at > now + timedelta(days=366):
        return "Reminders can be up to a year ahead."
    with _lock:
        items = _load()
        if len(items) >= MAX_PENDING:
            return "There are too many reminders waiting already. Cancel some first."
        items.append({"id": uuid.uuid4().hex[:8], "at": at.isoformat(timespec="minutes"),
                      "what": what})
        items.sort(key=lambda r: r["at"])
        _save(items)
    _ensure_watcher()
    print(f"[tool] reminder for {at:%Y-%m-%d %H:%M}: {what}", flush=True)
    return f"Reminder set for {_pretty(at, now)}: {what}."


def list_reminders():
    items = _load()
    if not items:
        return "No reminders are set."
    now = datetime.now()
    return "Reminders:\n" + "\n".join(
        f"- {_pretty(datetime.fromisoformat(r['at']), now)}: {r['what']}" for r in items)


def cancel_reminder(what):
    words = set((what or "").lower().split())
    with _lock:
        items = _load()
        best, score = None, 0
        for r in items:
            s = len(words & set(r["what"].lower().split()))
            if s > score:
                best, score = r, s
        if best is None:
            return "Couldn't find a reminder like that."
        items.remove(best)
        _save(items)
    print(f"[tool] cancelled reminder: {best['what']}", flush=True)
    return f"Cancelled the reminder for {_pretty(datetime.fromisoformat(best['at']))}: {best['what']}."


def due(now=None):
    """Take the reminders that are due off the list and return them."""
    now = now or datetime.now()
    with _lock:
        items = _load()
        ready = [r for r in items if datetime.fromisoformat(r["at"]) <= now]
        if ready:
            _save([r for r in items if r not in ready])
    return ready


def announcement(reminder, now=None):
    now = now or datetime.now()
    at = datetime.fromisoformat(reminder["at"])
    late = (f" It was meant for {_pretty(at, now)}, but you weren't running then, "
            "so say it's late.") if now - at > LATE_AFTER else ""
    return (f"A reminder they asked for is due now: {reminder['what']}.{late} "
            "Remind them, in your own words, in one or two sentences.")


def _watch(announce):
    while True:
        for r in due():
            announce(announcement(r))
        time.sleep(CHECK_SECONDS)


_announce = None


def start(announce):
    """Start delivering through `announce(text)`, the same queue timers use."""
    global _announce
    _announce = announce
    _ensure_watcher()


def _ensure_watcher():
    global _watcher
    if _announce is None or (_watcher and _watcher.is_alive()):
        return
    _watcher = threading.Thread(target=_watch, args=(_announce,), daemon=True,
                                name="reminders")
    _watcher.start()


SPECS = [
    ("set_reminder", set_reminder, {
        "description": "Remind them of something at a set date and time, even days "
                       "ahead. Work the date out from the current date and time you "
                       "were given. For 'in 20 minutes' use set_timer instead.",
        "parameters": {"type": "object", "properties": {
            "when": {"type": "string",
                     "description": "Their local time as YYYY-MM-DD HH:MM, 24-hour."},
            "what": {"type": "string", "description": "What to remind them about."}},
            "required": ["when", "what"]}}),
    ("list_reminders", list_reminders, {
        "description": "The reminders that are set and still to come.",
        "parameters": {"type": "object", "properties": {}}}),
    ("cancel_reminder", cancel_reminder, {
        "description": "Cancel a reminder. Describe it in a few words; the closest "
                       "match is removed.",
        "parameters": {"type": "object", "properties": {
            "what": {"type": "string"}}, "required": ["what"]}}),
]
