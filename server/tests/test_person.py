"""The things that make her feel like a person: running jokes, the shape of
her day, and openers about her own life."""
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process import idle, rhythm, shared
from process.memory import extract, store


@pytest.fixture
def mem(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MEMORY_FILE", tmp_path / "memory.json")
    monkeypatch.setattr(shared, "enabled", lambda: False)


def test_a_running_joke_is_parsed_kept_and_shown_apart(mem):
    found = extract._parse('[{"joke": "You both call the user\'s laptop the space heater"}]')
    assert found == [{"joke": "You both call the user's laptop the space heater"}]
    store.add(found[0]["joke"], source=store.JOKE)
    store.add("The user has a cat")
    block = store.as_prompt_block()
    assert "Running jokes" in block and "space heater" in block
    assert block.index("The user has a cat") < block.index("Running jokes")


def test_jokes_dont_push_out_facts(mem):
    for i in range(store.MAX_JOKES + 5):
        store.add(f"You both joke about thing number {i} " + "x" * i, source=store.JOKE)
    store.add("The user has a cat")
    texts = [f["text"] for f in store.all_facts()]
    assert "The user has a cat" in texts
    assert sum(1 for f in store.all_facts() if f["source"] == store.JOKE) <= store.MAX_JOKES


def test_she_is_sleepy_late_and_slow_early_and_herself_in_the_day():
    assert "sleepy" in rhythm.note(now=datetime(2026, 11, 24, 23, 30), roll=1.0)
    assert "woken up" in rhythm.note(now=datetime(2026, 11, 24, 7, 0), roll=1.0)
    assert rhythm.note("hey you", now=datetime(2026, 11, 24, 14, 0), roll=1.0) == ""


def test_sometimes_she_was_busy_with_her_own_thing():
    out = rhythm.note("hey you", now=datetime(2026, 11, 24, 14, 0), roll=0.0)
    assert "middle of something" in out


def test_openers_are_sometimes_about_her_own_day():
    assert idle.opener_instruction(roll=1.0) == idle.OPENER_INSTRUCTION
    own = idle.opener_instruction(roll=0.0)
    assert own.startswith(idle.OPENER_INSTRUCTION) and "your own day" in own
