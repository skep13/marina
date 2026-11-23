"""Their calendar from wherever the bridge is running.

On the Mac it's Calendar itself (process.tools.desk). On the bridge in the
lab, with no Calendar app, it's iCloud over CalDAV: the same calendars,
read with an app-specific password, so "what's on tomorrow?" works from the
phone.

Set up with `calendar.icloud_user` (their Apple ID email) in
character_config.yaml and the app-specific password, made at
account.apple.com > Sign-In and Security > App-Specific Passwords, in a
file `icloud.secret` next to it (one line, nothing else). It can only read.
"""
import re
import sys
import threading
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone

import requests

from process.config import resolve_data, setting

ROOT = "https://caldav.icloud.com/"
TIMEOUT = 15
NS = {"d": "DAV:", "c": "urn:ietf:params:xml:ns:caldav",
      "cs": "http://calendarserver.org/ns/", "ic": "http://apple.com/ns/ical/"}
# Calendars found are kept for a while; finding them is three round trips.
FIND_EVERY = 6 * 3600

_lock = threading.Lock()
_found = {"at": 0.0, "calendars": []}


def _user():
    return str(setting("calendar", "icloud_user", "") or "").strip()


def _password():
    path = setting("calendar", "icloud_secret_file", "icloud.secret") or "icloud.secret"
    try:
        return resolve_data(path).read_text().strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def icloud_ready():
    return bool(_user() and _password())


def _mac_ready():
    if sys.platform != "darwin":
        return False
    from process.tools import desk
    return desk.available("calendar")


def available():
    return bool(setting("tools", "calendar", True)) and (_mac_ready() or icloud_ready())


# ---- CalDAV ------------------------------------------------------------------

def _dav(method, url, body, depth="0"):
    r = requests.request(method, url, data=body.encode(), auth=(_user(), _password()),
                         headers={"Depth": depth,
                                  "Content-Type": "application/xml; charset=utf-8"},
                         timeout=TIMEOUT)
    if r.status_code == 401:
        raise RuntimeError("iCloud turned the password down. Make a new app-specific "
                           "password and put it in icloud.secret.")
    if r.status_code not in (200, 207):
        raise RuntimeError(f"iCloud answered {r.status_code}")
    return ET.fromstring(r.content), r.url


def _href(tree, prop):
    el = tree.find(f".//{prop}/d:href", NS)
    return el.text.strip() if el is not None and el.text else None


def _calendars():
    with _lock:
        if _found["calendars"] and time.time() - _found["at"] < FIND_EVERY:
            return _found["calendars"]
    tree, base = _dav("PROPFIND", ROOT, '<d:propfind xmlns:d="DAV:"><d:prop>'
                      "<d:current-user-principal/></d:prop></d:propfind>")
    principal = requests.compat.urljoin(base, _href(tree, "d:current-user-principal"))
    tree, base = _dav("PROPFIND", principal,
                      '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                      "<d:prop><c:calendar-home-set/></d:prop></d:propfind>")
    home = requests.compat.urljoin(base, _href(tree, "c:calendar-home-set"))
    tree, base = _dav("PROPFIND", home,
                      '<d:propfind xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">'
                      "<d:prop><d:displayname/><d:resourcetype/>"
                      "<c:supported-calendar-component-set/></d:prop></d:propfind>", "1")
    skip = [s.lower() for s in (setting("calendar", "skip", []) or [])]
    found = []
    for resp in tree.findall("d:response", NS):
        if resp.find(".//d:resourcetype/c:calendar", NS) is None:
            continue
        comps = {c.get("name") for c in resp.findall(".//c:comp", NS)}
        if comps and "VEVENT" not in comps:
            continue          # a reminders list, not a calendar
        name = (resp.findtext(".//d:displayname", "", NS) or "").strip()
        if any(s in name.lower() for s in skip):
            continue
        found.append((name, requests.compat.urljoin(base, resp.findtext("d:href", "", NS))))
    with _lock:
        _found.update(at=time.time(), calendars=found)
    return found


_QUERY = """<c:calendar-query xmlns:d="DAV:" xmlns:c="urn:ietf:params:xml:ns:caldav">
 <d:prop><c:calendar-data><c:expand start="{s}" end="{e}"/></c:calendar-data></d:prop>
 <c:filter><c:comp-filter name="VCALENDAR"><c:comp-filter name="VEVENT">
  <c:time-range start="{s}" end="{e}"/></c:comp-filter></c:comp-filter></c:filter>
</c:calendar-query>"""


def _unfold(ics):
    return re.sub(r"\r?\n[ \t]", "", ics).splitlines()


def _when(line):
    """(datetime in local time, all_day) from a DTSTART/DTEND line."""
    head, _, value = line.partition(":")
    value = value.strip()
    if "VALUE=DATE" in head or re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value[:8], "%Y%m%d"), True
    if value.endswith("Z"):
        at = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        return at.astimezone().replace(tzinfo=None), False
    return datetime.strptime(value[:15], "%Y%m%dT%H%M%S"), False


def _unescape(text):
    return (text.replace("\\n", " ").replace("\\,", ",").replace("\\;", ";")
            .replace("\\\\", "\\").strip())


def parse_events(ics, calendar_name):
    events, cur = [], None
    for line in _unfold(ics):
        if line == "BEGIN:VEVENT":
            cur = {"calendar": calendar_name, "title": "", "location": "",
                   "start": None, "end": None, "all_day": False}
        elif line == "END:VEVENT" and cur is not None:
            if cur["start"]:
                cur["end"] = cur["end"] or cur["start"] + (
                    timedelta(days=1) if cur["all_day"] else timedelta(hours=1))
                events.append(cur)
            cur = None
        elif cur is not None:
            key = line.split(":", 1)[0].split(";", 1)[0]
            if key == "SUMMARY":
                cur["title"] = _unescape(line.split(":", 1)[1])
            elif key == "LOCATION":
                cur["location"] = _unescape(line.split(":", 1)[1])
            elif key == "DTSTART":
                cur["start"], cur["all_day"] = _when(line)
            elif key == "DTEND":
                cur["end"], _ = _when(line)
    return events


def _icloud_events(start, end):
    fmt = "%Y%m%dT%H%M%SZ"
    s = start.astimezone(timezone.utc).strftime(fmt)
    e = end.astimezone(timezone.utc).strftime(fmt)
    events = []
    for name, url in _calendars():
        tree, _ = _dav("REPORT", url, _QUERY.format(s=s, e=e), "1")
        for data in tree.iter(f"{{{NS['c']}}}calendar-data"):
            if data.text:
                events += parse_events(data.text, name)
    return events


def calendar(days=1, start_date=""):
    if _mac_ready():
        from process.tools import desk
        return desk.calendar(days, start_date)
    if not icloud_ready():
        return ("Their calendar isn't connected here. It needs calendar.icloud_user "
                "in the config and an app-specific password in icloud.secret.")
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
        events = _icloud_events(start, end)
    except (requests.RequestException, RuntimeError, ET.ParseError) as e:
        return f"Couldn't read the calendar: {e}"
    # An all-day event that ended before the window, by iCloud's reckoning in UTC.
    events = [ev for ev in events if ev["end"] > start and ev["start"] < end]
    print(f"[tool] read iCloud calendar ({len(events)} events)", flush=True)
    from process.tools import desk
    return desk.format_events(events, start, days)


def today():
    if not available():
        return ""
    return calendar(1)


SPECS = [
    ("calendar", calendar, {
        "description": "Read their calendar: what's on today, tomorrow or the next "
                       "few days. Read-only.",
        "parameters": {"type": "object", "properties": {
            "days": {"type": "integer", "description": "How many days, from start_date."},
            "start_date": {"type": "string",
                           "description": "YYYY-MM-DD; empty for today."}}}}),
]
