"""The first time they talk to her each day, she catches them up: the
weather, what's on the calendar, reminders due today, the lists, and
anything wrong in the lab.

It rides on their first message as a turn note, so she works it into her
reply in her own voice rather than reading out a report, and it happens
once a day wherever they talk to her first (phone, Mac). The day turns over
at 4am, so talking at 1am still counts as the night before.

`brief:` in character_config.yaml turns it off or trims what goes in.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from process import config

DAY_STARTS = 4          # o'clock
STATE_KEY = "brief_last_day"
_lock = threading.Lock()


def _on(part):
    return bool(config.setting("brief", part, True))


def _today(now=None):
    now = now or datetime.now()
    return (now - timedelta(hours=DAY_STARTS)).date().isoformat()


def _weather():
    from process.tools import lookup
    if not config.setting("weather", "location", ""):
        return ""
    text = lookup.weather("", 1)
    lines = [l for l in text.splitlines()[1:] if l.strip()]
    return " ".join(lines) if lines and not text.startswith("Couldn") else ""


def _calendar():
    from process.tools import calendar_source
    text = calendar_source.today()
    if not text or text.startswith(("Couldn", "Marina isn't", "Calendar took", "Nothing on",
                                    "Their calendar isn't")):
        return ""
    return text


def _reminders(now=None):
    from process.tools import reminders
    now = now or datetime.now()
    end = datetime.combine(now.date() + timedelta(days=1), datetime.min.time()) \
        + timedelta(hours=DAY_STARTS)
    due = [r for r in reminders._load()
           if datetime.fromisoformat(r["at"]) < end]
    if not due:
        return ""
    return "Reminders still to come today: " + "; ".join(
        f"{datetime.fromisoformat(r['at']):%-I:%M %p} {r['what']}" for r in due) + "."


def _lists():
    from process.tools import lists
    line = lists.brief()
    return f"Their lists: {line}." if line else ""


def _lab():
    from process.tools import lab_health
    line = lab_health.brief()
    return f"Trouble {line}." if line else ""


_PARTS = [("weather", _weather), ("calendar", _calendar), ("reminders", _reminders),
          ("lists", _lists), ("lab", _lab)]


def gather():
    """Each part's line, gathered side by side; a part that fails is left out."""
    wanted = [(name, fn) for name, fn in _PARTS if _on(name)]
    out = {}
    with ThreadPoolExecutor(max_workers=len(wanted) or 1) as pool:
        jobs = {name: pool.submit(fn) for name, fn in wanted}
        for name, job in jobs.items():
            try:
                out[name] = job.result(timeout=15) or ""
            except Exception as e:
                print(f"[brief] {name} failed: {type(e).__name__}: {e}", flush=True)
                out[name] = ""
    return [out[name] for name, _ in wanted if out.get(name)]


def note(now=None):
    """The brief as a turn note, once a day, else ""."""
    if not _on("enabled"):
        return ""
    from process import state
    day = _today(now)
    with _lock:
        if state.get(STATE_KEY) == day:
            return ""
        state.put(STATE_KEY, day)
    try:
        lines = gather()
    except Exception as e:
        print(f"[brief] couldn't gather: {e}", flush=True)
        return ""
    if not lines:
        return ""
    hour = (now or datetime.now()).hour
    when = ("morning" if DAY_STARTS <= hour < 12 else
            "afternoon" if hour < 18 else "evening")
    print(f"[brief] {len(lines)} parts for {day}", flush=True)
    return ("\n\n(This is the first time they've talked to you today. You're "
            "their friend, not their secretary: answer them first, then mention "
            f"whatever from their {when} is actually worth a friend saying, the "
            "way a mate would (\"also it's going to chuck it down later\"). One or "
            "two casual sentences at most, skip the rest, never a rundown. If "
            "nothing here is interesting, say nothing about it. What you know:\n"
            + "\n".join(f"- {l}" for l in lines) + ")")
