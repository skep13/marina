from datetime import date

import pytest

from process.memory import extract, followup, store


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MEMORY_FILE", tmp_path / "memory.json")
    monkeypatch.setattr(store.shared, "enabled", lambda: False)
    monkeypatch.setattr(followup, "setting", lambda s, k, d=None: d)
    return store


def test_an_event_is_only_kept_with_a_day_still_to_come():
    today = date(2026, 10, 12)
    raw = ('[{"event": "The user has their driving test", "on": "2026-10-13"},'
           ' {"event": "The user went to a gig", "on": "2026-10-01"},'
           ' {"event": "The user has an exam", "on": "soon"},'
           ' "The user has a cat named Mochi"]')
    assert extract._parse(raw, today) == [
        {"event": "The user has their driving test", "on": "2026-10-13"},
        "The user has a cat named Mochi"]


def test_nothing_before_the_day_then_she_asks_after(memory):
    memory.add("The user has their driving test", source=store.EVENT, due="2026-10-13")
    assert followup.note(date(2026, 10, 12)) == ""
    assert "That is today" in followup.note(date(2026, 10, 13))
    after = followup.note(date(2026, 10, 14))
    assert "driving test" in after and "yesterday" in after and "how it went" in after


def test_she_gets_two_chances_then_lets_it_go(memory):
    memory.add("The user has their driving test", source=store.EVENT, due="2026-10-13")
    day = date(2026, 10, 15)
    assert "on Tuesday" in followup.note(day)
    assert followup.note(day)
    assert followup.note(day) == ""
    assert memory.events() == []


def test_too_old_to_ask_about_is_dropped(memory):
    memory.add("The user has their driving test", source=store.EVENT, due="2026-10-01")
    assert followup.note(date(2026, 10, 20)) == ""
    assert memory.events() == []


def test_events_stay_out_of_the_facts_she_is_shown(memory):
    memory.add("The user has their driving test", source=store.EVENT, due="2026-10-13")
    memory.add("The user has a cat named Mochi")
    block = memory.as_prompt_block()
    assert "Mochi" in block and "driving test" not in block
