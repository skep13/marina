"""Reminders persist, fire once, and say so when they come back late."""
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process.tools import reminders


def test_reminder_times_are_read_in_local_time():
    assert reminders.parse_when("2026-10-22 15:00") == datetime(2026, 10, 22, 15, 0)
    assert reminders.parse_when("2026-10-22T15:00") == datetime(2026, 10, 22, 15, 0)
    assert reminders.parse_when("2026-10-22 3:30 pm") == datetime(2026, 10, 22, 15, 30)
    assert reminders.parse_when("2026-10-22") == datetime(2026, 10, 22, 9, 0)
    assert reminders.parse_when("Thursday at 3") is None


def test_reminders_persist_and_fire_once(tmp_path, monkeypatch):
    monkeypatch.setattr(reminders, "FILE", tmp_path / "reminders.json")
    monkeypatch.setattr(reminders, "_ensure_watcher", lambda: None)
    soon = datetime.now() + timedelta(hours=2)
    later = datetime.now() + timedelta(days=3)
    assert "Reminder set" in reminders.set_reminder(soon.strftime("%Y-%m-%d %H:%M"), "call the dentist")
    assert "Reminder set" in reminders.set_reminder(later.strftime("%Y-%m-%d %H:%M"), "bins out")
    assert "already passed" in reminders.set_reminder("2020-01-01 10:00", "too late")
    assert "dentist" in reminders.list_reminders()

    assert reminders.due() == []
    fired = reminders.due(now=soon + timedelta(minutes=1))
    assert [r["what"] for r in fired] == ["call the dentist"]
    assert reminders.due(now=soon + timedelta(minutes=2)) == []

    assert "Cancelled" in reminders.cancel_reminder("bins")
    assert reminders.list_reminders() == "No reminders are set."


def test_a_missed_reminder_says_it_is_late():
    at = datetime(2026, 10, 20, 9, 0)
    on_time = reminders.announcement({"at": at.isoformat(), "what": "x"}, now=at)
    late = reminders.announcement({"at": at.isoformat(), "what": "x"}, now=at + timedelta(hours=3))
    assert "late" not in on_time
    assert "late" in late
