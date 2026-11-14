from types import SimpleNamespace

import pytest

from process import backend
from process.llm_funcs import llm_scr


def pieces(*texts):
    return [SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=t, tool_calls=None))]) for t in texts]


def a_call(name, arguments="{}"):
    fn = SimpleNamespace(name=name, arguments=arguments)
    call = SimpleNamespace(index=0, id="c1", function=fn)
    return SimpleNamespace(choices=[SimpleNamespace(
        delta=SimpleNamespace(content=None, tool_calls=[call]))])


@pytest.fixture
def rounds(monkeypatch):
    """Feed llm_stream one list of stream events per round."""
    class Rounds(list):
        pass
    queue, seen = Rounds(), []

    def fake(messages, working=False, **kw):
        seen.append({"working": working, "tools": kw.get("tools")})
        return queue.pop(0)

    offer = [{"type": "function", "function": {"name": "run", "parameters": {}}}]
    monkeypatch.setattr(llm_scr, "get_reply_stream", fake)
    monkeypatch.setattr(llm_scr, "system_message", lambda: {"role": "system", "content": "s"})
    monkeypatch.setattr(llm_scr, "turn_notes", lambda *a: "")
    monkeypatch.setattr(llm_scr.ambient, "as_note", lambda: "")
    monkeypatch.setattr(llm_scr.tools, "definitions", lambda: offer)
    monkeypatch.setattr(llm_scr.tools, "wants_long_loop", lambda: True)
    monkeypatch.setattr(llm_scr.tools, "describe", lambda n, a: ("", "vm"))
    monkeypatch.setattr(llm_scr.tools, "needs_ok", lambda n, a, c: None)
    monkeypatch.setattr(llm_scr.tools, "run", lambda n, a: "ok")
    monkeypatch.setattr(llm_scr, "_tools_supported", True)
    queue.seen = seen
    return queue


def say(user="hi"):
    return "".join(llm_scr.llm_stream(user, history=[]))


def test_reasoning_is_never_said_even_split_across_pieces():
    f = llm_scr._Unspoken()
    out = "".join(f.feed(p) for p in ["hey <th", "ink>the user wants", " x</thi", "nk>you ok", "?"])
    assert out + f.flush() == "hey you ok?"


def test_an_ordinary_reply_still_streams(rounds):
    rounds.append(pieces("yeah ", "no."))
    assert list(llm_scr.llm_stream("hi", history=[])) == ["yeah ", "no."]


def test_notes_to_herself_between_tool_calls_are_not_spoken(rounds):
    rounds.append(pieces("one sec.") + [a_call("run")])
    rounds.append(pieces("Now let me check the config step by step.") + [a_call("run", '{"a":1}')])
    rounds.append(pieces("</think>done, it's ", "dark now."))
    assert say("can you fix the theme") == "one sec.done, it's dark now."
    assert [r["working"] for r in rounds.seen] == [False, True, True]


def test_a_tool_call_written_as_text_is_run_not_read_out(rounds):
    ran = []
    llm_scr.tools.run = lambda n, a: ran.append((n, a)) or "ok"
    rounds.append(pieces('{"name": "run", ', '"arguments": {"cmd": "ls"}}'))
    rounds.append(pieces("three files in there."))
    assert say("can you check the folder") == "three files in there."
    assert ran == [("run", '{"cmd": "ls"}')]


def test_json_she_meant_to_say_is_still_said(rounds):
    rounds.append(pieces('{"mood": "bored"} is how i would log today'))
    assert say() == '{"mood": "bored"} is how i would log today'


def test_the_backup_model_gets_no_tools_and_is_told(monkeypatch):
    monkeypatch.setattr(llm_scr, "backend_mode", lambda: "auto")
    monkeypatch.setattr(backend, "NAMES", ("server", "local"))
    monkeypatch.setattr(llm_scr, "_recall", lambda: True)
    monkeypatch.setattr(llm_scr.config, "system_prompt", lambda: "You are Marina.")
    assert llm_scr._is_backup("local") and not llm_scr._is_backup("server")
    msgs = [{"role": "system", "content": "You are Marina. More."},
            {"role": "user", "content": "hi"}]
    sent, kw = llm_scr._for_backup(msgs, {"tools": [1], "tool_choice": "auto", "stream": True})
    assert kw == {"stream": True}
    assert sent[0]["content"].endswith(llm_scr.ON_BACKUP) and sent[1] == msgs[1]
    assert msgs[0]["content"] == "You are Marina. More."
    # A side job (pulling out facts) is left as it is.
    side, _ = llm_scr._for_backup([{"role": "system", "content": "Extract facts."}], {})
    assert side[0]["content"] == "Extract facts."


def test_her_fixed_profile_and_whose_is_whose_are_in_the_prompt(monkeypatch):
    from process.memory import persona
    values = {("persona", "profile"): ["You are 19.", "They built you, and you know it."]}
    monkeypatch.setattr(persona, "setting", lambda s, k, d=None: values.get((s, k), d))
    block = persona.profile_block()
    assert "- You are 19." in block and "whose life is whose" in block
    values[("persona", "enabled")] = False
    assert persona.profile_block() == ""
