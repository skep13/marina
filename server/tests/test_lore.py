import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from process.memory import lore


def chat(*texts):
    out = []
    for i, t in enumerate(texts):
        out.append({"role": "user" if i % 2 == 0 else "assistant", "content": t})
    return out


@pytest.fixture
def entries(tmp_path, monkeypatch):
    path = tmp_path / "lore.json"
    settings = {("lore", "enabled"): True, ("llm", "recall"): True,
                ("lore", "scan_depth"): 4, ("lore", "max_entries"): 3}
    monkeypatch.setattr(lore, "_path", lambda: path)
    monkeypatch.setattr(lore, "setting", lambda s, k, d=None: settings.get((s, k), d))
    lore.reset()

    def write(data):
        path.write_text(json.dumps(data))
        lore._cache["mtime"] = None
        return settings
    yield write
    lore.reset()


HACK = {"keys": ["hack club"], "text": "The meeting ran four hours late.", "cooldown": 3}


def test_fires_on_its_key_and_not_otherwise(entries):
    entries([HACK])
    assert lore.note([], "how was your day") == ""
    n = lore.note([], "the HACK  club meeting went well")
    assert "four hours late" in n and "Note to you" in n


def test_whole_words_only(entries):
    entries([{"keys": ["art"], "text": "You draw."}])
    assert lore.note([], "let's start") == ""
    assert "You draw." in lore.note([], "i made some art")


def test_regex_keys(entries):
    entries([{"keys": ["/climb(ing|ed)?/"], "text": "They climb."}])
    assert "They climb." in lore.note([], "went climbing today")


def test_scans_recent_history_including_her_replies(entries):
    entries([HACK])
    history = chat("hi", "how's hack club going?", "fine")
    assert "four hours" in lore.note(history, "yeah")


def test_ignores_messages_beyond_scan_depth(entries):
    settings = entries([HACK])
    settings[("lore", "scan_depth")] = 2
    history = chat("hack club stuff", "ok", "something", "else")
    assert lore.note(history, "hm") == ""


def test_cooldown_stops_retelling(entries):
    entries([HACK])
    said = [bool(lore.note([], "hack club")) for _ in range(6)]
    # fires, rests for 3 replies, then may fire again
    assert said == [True, False, False, False, True, False]


def test_sticky_keeps_it_for_following_replies(entries):
    entries([dict(HACK, sticky=2, cooldown=10)])
    assert lore.note([], "hack club")
    assert lore.note([], "anyway")          # still in front of her
    assert lore.note([], "anyway") == ""


def test_probability_gate(entries):
    entries([dict(HACK, probability=0.5)])
    assert lore.triggered([], "hack club", roll=lambda: 0.9) == []
    assert lore.triggered([], "hack club", roll=lambda: 0.1)


def test_constant_entries_always_present_and_first(entries):
    entries([HACK, {"constant": True, "text": "Partners."}])
    found = lore.triggered([], "hack club")
    assert [e["text"] for e in found] == ["Partners.", "The meeting ran four hours late."]
    assert lore.triggered([], "nothing")[0]["text"] == "Partners."


def test_max_entries_keeps_highest_priority(entries):
    settings = entries([{"keys": ["a1"], "text": "low"},
                        {"keys": ["a1"], "text": "high", "priority": 5}])
    settings[("lore", "max_entries")] = 1
    assert [e["text"] for e in lore.triggered([], "a1")] == ["high"]


def test_off_when_recall_is_off(entries):
    settings = entries([HACK])
    settings[("llm", "recall")] = False
    assert lore.note([], "hack club") == ""


def test_bad_or_missing_file_is_harmless(entries, tmp_path):
    assert lore.note([], "hack club") == ""      # no file yet
    (tmp_path / "lore.json").write_text("{not json")
    lore._cache["mtime"] = None
    assert lore.note([], "hack club") == ""
    entries([{"text": "no keys and not constant"}, {"keys": ["x"], "text": "  "}])
    assert lore.entries() == []


def test_accepts_entries_wrapper_and_comma_keys(entries):
    entries({"entries": [{"keys": "birthday, bday", "text": "A day late."}]})
    assert lore.note([], "my bday is soon")


def test_example_file_loads():
    raw = json.loads((Path(__file__).resolve().parents[2] / "lore.example.json").read_text())
    assert len(lore._normalise(raw)) == len(raw)
