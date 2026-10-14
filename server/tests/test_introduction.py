"""Asked to introduce Hack Club, she gives the fixed intro without the model."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process.llm_funcs import llm_scr
from process.llm_funcs.llm_scr import INTRODUCTION, scripted_reply


def test_spots_the_question_however_it_is_asked():
    assert scripted_reply("introduce hack club") == INTRODUCTION
    assert scripted_reply("Marina, can you introduce Hack Club to the class?") == INTRODUCTION
    assert scripted_reply("Introduce Hackclub.") == INTRODUCTION
    assert scripted_reply("hey marina introduce hack-club please") == INTRODUCTION


def test_leaves_other_messages_to_the_model():
    assert scripted_reply("introduce yourself") is None
    assert scripted_reply("what is hack club") is None
    assert scripted_reply("how was your day") is None
    assert scripted_reply(None) is None
    assert scripted_reply([{"type": "text", "text": "introduce hack club"}]) is None


def test_stream_skips_the_model(monkeypatch):
    def no_model(*a, **kw):
        raise AssertionError("the model was called")
    monkeypatch.setattr(llm_scr, "get_reply_stream", no_model)
    assert "".join(llm_scr.llm_stream("Introduce Hack Club!")) == INTRODUCTION
