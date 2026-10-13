"""She can forget a fact, and keep notes about herself next to the facts
about them."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process import shared
from process.memory import store
from process.tools import registry


@pytest.fixture
def mem(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MEMORY_FILE", tmp_path / "memory.json")
    monkeypatch.setattr(shared, "enabled", lambda: False)


def test_forget_removes_the_closest_fact(mem):
    store.add("The user is good at climbing")
    store.add("The user uses Kubuntu")
    assert "climbing" in registry.forget("climbing")
    assert [f["text"] for f in store.all_facts()] == ["The user uses Kubuntu"]
    assert "Couldn't find" in registry.forget("their favourite pizza")


def test_notes_about_herself_are_kept_and_shown_apart(mem):
    registry.note_to_self("Marina thinks Bunny Girl Senpai is the best anime")
    registry.note_to_self("she's been theming her desktop purple")
    store.add("The user uses Kubuntu")
    block = store.as_prompt_block()
    about_them, about_her = block.split("Notes you've kept about yourself")
    assert "Kubuntu" in about_them and "Bunny Girl" not in about_them
    assert "Marina thinks Bunny Girl Senpai" in about_her
    assert "Marina: she's been theming" in about_her
