import json
from types import SimpleNamespace as NS

from process import narwhal


def chunk(content=None, reasoning=None):
    delta = NS(content=content, reasoning_content=reasoning, model_extra={})
    return NS(choices=[NS(delta=delta)])


class FakeClient:
    def __init__(self, chunks, boom=None):
        self.sent = None
        self.chat = NS(completions=NS(create=self.create))
        self._chunks, self._boom = chunks, boom

    def create(self, **kw):
        self.sent = kw
        if self._boom:
            raise self._boom
        return iter(self._chunks)


def events(gen):
    return [json.loads(line) for line in gen]


def test_streams_reasoning_and_text():
    c = FakeClient([chunk(reasoning="hmm "), chunk(reasoning="ok"), chunk("Three "), chunk("hosts.")])
    ev = events(narwhal.stream(c, [{"role": "user", "content": "scan"}]))
    assert ev[0]["type"] == "start"
    assert "".join(e["text"] for e in ev if e["type"] == "think") == "hmm ok"
    assert "".join(e["text"] for e in ev if e["type"] == "text") == "Three hosts."
    assert ev[-1]["type"] == "done" and ev[-1]["chars"] == len("Three hosts.")
    assert c.sent["model"] == "narwhal" and c.sent["stream"] is True


def test_inline_think_tags_split_across_chunks():
    c = FakeClient([chunk("<thi"), chunk("nk>plan</th"), chunk("ink>Answer")])
    ev = events(narwhal.stream(c, [{"role": "user", "content": "q"}]))
    assert "".join(e["text"] for e in ev if e["type"] == "think") == "plan"
    assert "".join(e["text"] for e in ev if e["type"] == "text") == "Answer"


def test_clean_drops_other_roles_and_leading_assistant():
    out = narwhal.clean([{"role": "assistant", "content": "hi"}, {"role": "system", "content": "x"},
                         {"role": "user", "content": " a "}, {"role": "tool", "content": "t"},
                         {"role": "assistant", "content": ""}])
    assert out == [{"role": "user", "content": "a"}]


def test_error_is_an_event():
    c = FakeClient([], boom=RuntimeError("down"))
    ev = events(narwhal.stream(c, [{"role": "user", "content": "q"}], lambda e: f"bad: {e}"))
    assert ev[-1] == {"type": "error", "message": "bad: down"}


def test_empty_conversation():
    ev = events(narwhal.stream(FakeClient([]), []))
    assert ev == [{"type": "error", "message": "Nothing to send."}]
