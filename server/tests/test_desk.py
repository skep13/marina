"""How the calendar reads out."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process.tools import desk


def test_calendar_reads_in_order_without_hidden_calendars():
    day = datetime(2026, 10, 20)
    events = [
        {"calendar": "Work", "title": "Standup", "start": day.replace(hour=9, minute=30),
         "end": day.replace(hour=9, minute=45), "all_day": False, "location": ""},
        {"calendar": "Siri Suggestions", "title": "Guess", "start": day.replace(hour=8),
         "end": day.replace(hour=9), "all_day": False, "location": ""},
        {"calendar": "Home", "title": "Mum's birthday", "start": day, "end": day + timedelta(days=1),
         "all_day": True, "location": "Leeds"},
    ]
    out = desk.format_events(events, day, 1)
    assert out.splitlines() == [
        "On the calendar for today:",
        "- Tue 20 Oct, all day: Mum's birthday at Leeds",
        "- Tue 20 Oct, 09:30–09:45: Standup",
    ]
    assert desk.format_events([], day, 3) == "Nothing on the calendar for the next 3 days."
