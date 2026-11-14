import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from process.llm_funcs import style


@pytest.fixture
def every(monkeypatch):
    value = {"n": 3}
    monkeypatch.setattr(style, "setting", lambda s, k, d=None: value["n"] if (s, k) == ("llm", "action_every") else d)
    return value


def her(*replies):
    out = []
    for r in replies:
        out += [{"role": "user", "content": "hi"}, {"role": "assistant", "content": r}]
    return out


def streamed(reply, history, size=3):
    p = style.Pacer(history)
    out = [p.feed(reply[i:i + size]) for i in range(0, len(reply), size)]
    return "".join(out) + p.flush()


def test_off_by_default_keeps_everything(every):
    every["n"] = 0
    assert style.pace("*grins*\n\nHey.", her("*nods* ok")) == "*grins*\n\nHey."


def test_first_gesture_is_allowed(every):
    assert style.pace("*grins*\n\nFour hours?", her("Sure.", "Fine.")) == "*grins*\n\nFour hours?"


def test_gesture_dropped_when_one_was_recent(every):
    history = her("*smirks*\n\nStop.", "Okay.")
    assert style.pace("*tilts head*\n\nWhy?", history) == "Why?"
    assert streamed("*tilts head*\n\nWhy? Do I sound old?", history) == "Why? Do I sound old?"


def test_allowed_again_after_the_gap(every):
    assert style.pace("*waves* Hi.", her("*smirks* no", "Okay.", "Sure.")) == "*waves* Hi."


def test_emphasis_is_not_a_gesture(every):
    history = her("*smirks* no", "ok")
    assert style.pace("*so* not fair.", history) == "*so* not fair."
    assert streamed("*so* not fair.", history) == "*so* not fair."
    assert streamed("**Bold** start here", history) == "**Bold** start here"


def test_a_gesture_alone_is_kept(every):
    history = her("*smirks* no", "ok")
    assert style.pace("*shrugs*", history) == "*shrugs*"
    assert streamed("*shrugs*", history) == "*shrugs*"


def test_inline_gestures_are_left_alone(every):
    history = her("*smirks* no", "ok")
    assert style.pace("Fine. *rolls eyes* Whatever.", history) == "Fine. *rolls eyes* Whatever."
    assert streamed("Fine. *rolls eyes* Whatever.", history) == "Fine. *rolls eyes* Whatever."


def test_stream_passes_plain_replies_straight_through(every):
    p = style.Pacer(her("*smirks* no"))
    assert p.feed("Hey") == "Hey"
    assert p.feed(" there") == " there"
