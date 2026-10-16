"""Their calendar and what's playing, on a bridge running on their Mac.

Both are read-mostly and low risk, so they are on by default and don't
need `mac.enabled`, which hands her the whole machine.

The calendar is read with EventKit when the bridge already has full
calendar access, because EventKit expands repeating events. Otherwise it asks
Calendar over AppleScript, which only needs the Automation permission the app
already asks for, but lists a repeating event only on its first day.
"""
import json
import subprocess
import sys
from datetime import date, datetime, timedelta

from process.config import setting

TIMEOUT = 30
MAX_EVENTS = 40


def _on(key):
    return sys.platform == "darwin" and bool(setting("tools", key, True))


def _osascript(script, *args, language="AppleScript"):
    out = subprocess.run(["osascript", "-l", language, "-e", script, *args],
                         capture_output=True, text=True, timeout=TIMEOUT)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or "osascript failed").strip())
    return out.stdout.strip()


# --- calendar ---------------------------------------------------------------

_EVENTKIT = """
ObjC.import('EventKit');
function run(argv) {
  if ($.EKEventStore.authorizationStatusForEntityType($.EKEntityTypeEvent) != 3)
    return 'NO_ACCESS';
  const store = $.EKEventStore.alloc.init;
  const start = $.NSDate.dateWithTimeIntervalSince1970(Number(argv[0]));
  const end = $.NSDate.dateWithTimeIntervalSince1970(Number(argv[1]));
  const found = store.eventsMatchingPredicate(
    store.predicateForEventsWithStartDateEndDateCalendars(start, end, $()));
  const out = [];
  for (let i = 0; i < found.count; i++) {
    const e = found.objectAtIndex(i);
    out.push({title: ObjC.unwrap(e.title) || '', calendar: ObjC.unwrap(e.calendar.title) || '',
              start: e.startDate.timeIntervalSince1970, end: e.endDate.timeIntervalSince1970,
              allDay: !!e.allDay, location: ObjC.unwrap(e.location) || ''});
  }
  return JSON.stringify(out);
}
"""

_APPLESCRIPT = """
on run argv
	-- Offsets in seconds from now, prefixed with "s" so osascript doesn't
	-- take a negative one for an option.
	set startD to (current date) + ((text 2 thru -1 of item 1 of argv) as integer)
	set endD to (current date) + ((text 2 thru -1 of item 2 of argv) as integer)
	set AppleScript's text item delimiters to ","
	set skipped to text items of (item 3 of argv)
	set out to ""
	tell application "Calendar"
		repeat with c in calendars
			set cname to name of c
			set skip to false
			repeat with s in skipped
				if (length of s) > 0 and cname contains s then set skip to true
			end repeat
			if not skip then
				repeat with e in (every event of c whose start date < endD and end date > startD)
					set loc to location of e
					if loc is missing value then set loc to ""
					set out to out & cname & tab & (summary of e) & tab & ¬
						((start date of e) as «class isot» as string) & tab & ¬
						((end date of e) as «class isot» as string) & tab & ¬
						(allday event of e) & tab & loc & linefeed
				end repeat
			end if
		end repeat
	end tell
	return out
end run
"""


def _events_eventkit(start, end):
    raw = _osascript(_EVENTKIT, str(start.timestamp()), str(end.timestamp()),
                     language="JavaScript")
    if raw == "NO_ACCESS":
        return None
    return [{"title": e["title"], "calendar": e["calendar"],
             "start": datetime.fromtimestamp(float(e["start"])),
             "end": datetime.fromtimestamp(float(e["end"])),
             "all_day": e["allDay"], "location": e["location"]}
            for e in json.loads(raw or "[]")]


def _events_applescript(start, end):
    now = datetime.now()
    raw = _osascript(_APPLESCRIPT, f"s{int((start - now).total_seconds())}",
                     f"s{int((end - now).total_seconds())}", _skipped())
    events = []
    for line in raw.splitlines():
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        events.append({"calendar": parts[0], "title": parts[1],
                       "start": datetime.fromisoformat(parts[2]),
                       "end": datetime.fromisoformat(parts[3]),
                       "all_day": parts[4] == "true",
                       "location": parts[5] if len(parts) > 5 else ""})
    return events


_HIDDEN = {"siri suggestions", "scheduled reminders"}

# Subscribed holiday calendars take Calendar many seconds each over
# AppleScript, so they're left out there unless the config says otherwise.
SKIP_DEFAULT = ["Holiday", "Siri Suggestions", "Scheduled Reminders"]


def _skipped():
    skip = setting("calendar", "skip", SKIP_DEFAULT)
    return ",".join(str(s).replace(",", " ") for s in (skip or []))


def format_events(events, start, days):
    events = sorted((e for e in events if e["calendar"].lower() not in _HIDDEN),
                    key=lambda e: (e["start"], not e["all_day"]))
    span = "today" if days == 1 else f"the next {days} days"
    if not events:
        return f"Nothing on the calendar for {span}."
    lines = [f"On the calendar for {span}:"]
    for e in events[:MAX_EVENTS]:
        day = e["start"].strftime("%a %-d %b")
        when = ("all day" if e["all_day"]
                else f"{e['start']:%H:%M}–{e['end']:%H:%M}")
        where = f" at {e['location']}" if e["location"] else ""
        lines.append(f"- {day}, {when}: {e['title']}{where}")
    if len(events) > MAX_EVENTS:
        lines.append(f"…and {len(events) - MAX_EVENTS} more.")
    return "\n".join(lines)


def calendar(days=1, start_date=""):
    try:
        days = max(1, min(int(days), 31))
    except (TypeError, ValueError):
        days = 1
    try:
        first = date.fromisoformat(start_date) if start_date else date.today()
    except ValueError:
        return "start_date has to be YYYY-MM-DD."
    start = datetime.combine(first, datetime.min.time())
    end = start + timedelta(days=days)
    try:
        events = _events_eventkit(start, end)
        if events is None:
            events = _events_applescript(start, end)
    except subprocess.TimeoutExpired:
        return "Calendar took too long to answer."
    except RuntimeError as e:
        if "-1743" in str(e) or "Not authorized" in str(e):
            return ("Marina isn't allowed to read Calendar. They can allow it in "
                    "System Settings > Privacy & Security > Automation.")
        return f"Couldn't read the calendar: {e}"
    print(f"[tool] read the calendar ({len(events)} events)", flush=True)
    return format_events(events, start, days)


# --- media ------------------------------------------------------------------

_PLAYERS = ("Spotify", "Music")

_NOW_PLAYING = """
on run argv
	set p to item 1 of argv
	using terms from application "Music"
		tell application p
			if player state is stopped then return "stopped"
			set t to current track
			return (player state as string) & tab & (name of t) & tab & (artist of t) & tab & (album of t)
		end tell
	end using terms from
end run
"""

_COMMANDS = {
    "play": "play", "pause": "pause", "toggle": "playpause",
    "next": "next track", "previous": "previous track",
}


def _running_player():
    try:
        out = _osascript('tell application "System Events" to get name of '
                         'every process whose background only is false')
    except (RuntimeError, subprocess.TimeoutExpired):
        return None
    running = {name.strip() for name in out.split(",")}
    return next((p for p in _PLAYERS if p in running), None)


def media(action="now_playing"):
    action = (action or "now_playing").strip().lower().replace(" ", "_")
    if action not in _COMMANDS and action != "now_playing":
        return f"Unknown action {action!r}. Use now_playing, play, pause, toggle, next or previous."
    player = _running_player()
    if not player:
        return "Neither Spotify nor Music is open."
    try:
        if action != "now_playing":
            _osascript(f'tell application "{player}" to {_COMMANDS[action]}')
        state = _osascript(_NOW_PLAYING, player)
    except subprocess.TimeoutExpired:
        return f"{player} didn't answer."
    except RuntimeError as e:
        if "-1743" in str(e):
            return (f"Marina isn't allowed to control {player}. They can allow it in "
                    "System Settings > Privacy & Security > Automation.")
        return f"Couldn't talk to {player}: {e}"
    print(f"[tool] media {action} in {player}", flush=True)
    if state == "stopped":
        return f"{player} is stopped."
    parts = state.split("\t")
    status, track, artist = parts[0], parts[1], parts[2] if len(parts) > 2 else ""
    return f"{player} is {status}: {track}{f' by {artist}' if artist else ''}."


SPECS = [
    ("calendar", calendar, "calendar", {
        "description": "What's on their calendar: meetings, plans, appointments. "
                       "Check it before saying whether they're free.",
        "parameters": {"type": "object", "properties": {
            "days": {"type": "integer", "description": "How many days to cover, from start_date. Default 1."},
            "start_date": {"type": "string", "description": "YYYY-MM-DD; default today."}}}}),
    ("media", media, "media", {
        "description": "See what's playing in Spotify or Music, or control it.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string",
                       "enum": ["now_playing", "play", "pause", "toggle", "next", "previous"]}},
            "required": ["action"]}}),
]


def available(key):
    return _on(key)
