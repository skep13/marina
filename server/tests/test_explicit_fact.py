"""'Remember ...' requests are saved straight from the user's words, so she
doesn't need to call the remember tool for them to stick."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process.memory.extract import explicit_fact


def test_remember_that():
    assert explicit_fact("remember that my exam is on the 12th") == "The user's exam is on the 12th"


def test_plain_remember():
    assert explicit_fact("remember i hate mushrooms") == "The user hates mushrooms"


def test_dont_forget():
    assert explicit_fact("dont forget my mums birthday is march 3rd") == \
        "The user's mums birthday is march 3rd"


def test_remember_that_at_the_end():
    assert explicit_fact("oh btw i switched to arch linux, remember that") == \
        "The user switched to arch linux"


def test_remember_this_at_the_end():
    assert explicit_fact("I'm vegetarian now. Remember this") == "The user is vegetarian now"


def test_nothing_to_remember():
    assert explicit_fact("remember that") is None
    assert explicit_fact("how was your day?") is None


# "Forget ..." is handled the same way, so a wrong fact goes even when she
# doesn't call the forget tool.
import pytest

from process import shared
from process.memory import extract, store
from process.memory.extract import explicit_forget, forget_explicit


@pytest.fixture
def mem(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MEMORY_FILE", tmp_path / "memory.json")
    monkeypatch.setattr(shared, "enabled", lambda: False)
    monkeypatch.setattr(store, "last_removed", 0.0)


def test_what_to_forget():
    assert explicit_forget("forget that i live in cardiff") == "i live in cardiff"
    assert explicit_forget("please forget about my exam, it got cancelled") == "my exam"
    assert explicit_forget("i dont live in cardiff anymore, forget that") == \
        "i dont live in cardiff anymore"
    assert explicit_forget("Ok. Can you forget my old address") == "my old address"


def test_not_a_forget_request():
    for text in ["don't forget my mums birthday", "i always forget my keys",
                 "nvm forget it", "forget it", "how was your day?",
                 "i forgot to eat lol"]:
        assert explicit_forget(text) is None, text


def test_forget_removes_the_fact(mem):
    store.add("The user lives in Cardiff")
    store.add("The user uses Kubuntu")
    assert forget_explicit("forget that i live in cardiff") == "The user lives in Cardiff"
    assert [f["text"] for f in store.all_facts()] == ["The user uses Kubuntu"]


def test_forget_leaves_unrelated_facts(mem):
    store.add("The user uses Kubuntu")
    assert forget_explicit("forget about my exam") is None
    assert [f["text"] for f in store.all_facts()] == ["The user uses Kubuntu"]


def test_no_second_removal_after_the_tool(mem):
    from process.tools import registry
    store.add("The user lives in Cardiff")
    store.add("The user lives with their cat in a flat")
    registry.forget("lives in Cardiff")          # she used the tool this turn
    assert forget_explicit("forget that i live in cardiff") is None
    assert len(store.all_facts()) == 1


def test_exclamation_before_forget_it_is_not_a_fact():
    assert explicit_forget("ugh, forget it") is None
    assert explicit_forget("never mind, forget it") is None
