import time
import json
import threading
from types import SimpleNamespace as NS

import pytest

from process import narwhal_route as nr
from process import narwhal_sessions as ns


def chunk(content=None, reasoning=None):
    return NS(choices=[NS(delta=NS(content=content, reasoning_content=reasoning, model_extra={}))])


class FakeClient:
    """Streams the given chunks; `gate` (an Event) holds the reply open
    after the first chunk so tests can watch it mid-reply."""

    def __init__(self, chunks=None, gate=None, boom=None):
        self.calls = []
        self.chunks = chunks or [chunk(reasoning="thinking"), chunk("Hello "), chunk("there.")]
        self.gate, self.boom = gate, boom
        self.chat = NS(completions=NS(create=self.create))

    def create(self, **kw):
        self.calls.append(kw)
        if self.boom:
            raise self.boom

        def gen():
            for i, c in enumerate(self.chunks):
                yield c
                if i == 0 and self.gate:
                    self.gate.wait(5)
        return gen()


@pytest.fixture
def hub(tmp_path):
    client = FakeClient()
    h = ns.Hub(path=tmp_path / "narwhal.db", client=lambda: client, error_message=lambda e: f"bad: {e}")
    h.fake = client
    return h


def send_and_wait(h, sid, text, route="auto"):
    out = h.send(sid, text, route)
    ns.wait_idle(h, sid)
    return out


# --- routing -------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "nmap scan of 10.0.0.0/24, which ports matter?",
    "Write a reverse shell payload for a CTF box",
    "How do I privesc from www-data on this Linux host?",
    "explain CVE-2024-3094 and how to exploit it",
    "write exploit code for this buffer overflow",
])
def test_security_messages_go_to_the_abliterated_model(text):
    route, _ = nr.choose(text)
    assert route == nr.SECURITY
    assert nr.model_for(route) == "narwhal"


@pytest.mark.parametrize("text", [
    "Refactor this Python function to use a dataclass",
    "Traceback (most recent call last):\n  File \"app.py\", line 3\nTypeError: bad",
    "My Rust build fails with a borrow checker error in main.rs",
    "write a unit test with pytest for parse_config",
    "```js\nconst x = 1;\nfunction f() { return x }\n```",
])
def test_coding_messages_go_to_kat_coder(text):
    route, _ = nr.choose(text)
    assert route == nr.CODE
    assert nr.model_for(route) == "forge"


def test_neutral_first_message_uses_the_default():
    assert nr.choose("hi, how are you?")[0] == nr.SECURITY


def test_follow_ups_stick_to_the_last_model():
    assert nr.choose("thanks, and the next step?", last=nr.CODE)[0] == nr.CODE
    assert nr.choose("ok go on", last=nr.SECURITY)[0] == nr.SECURITY
    # A light mention of the other side isn't worth a model swap.
    assert nr.choose("can you add a function for that", last=nr.SECURITY)[0] == nr.SECURITY


def test_a_clear_change_of_subject_switches():
    assert nr.choose("Refactor this Python class and add pytest unit tests", last=nr.SECURITY)[0] == nr.CODE
    assert nr.choose("now run an nmap port scan and look for privesc", last=nr.CODE)[0] == nr.SECURITY


def test_words_inside_other_words_dont_count():
    assert nr.scores("shellcode")[1] == 0       # "code" inside shellcode
    assert nr.scores("barcode scanner app")[0] == 0


def test_models_and_labels_come_from_config(monkeypatch):
    vals = {("narwhal", "code_model"): "kat", ("narwhal", "label"): "N"}
    monkeypatch.setattr(nr.cfg, "setting", lambda s, k, d=None: vals.get((s, k), d))
    assert nr.model_for(nr.CODE) == "kat" and nr.label_for(nr.SECURITY) == "N"


# --- sessions ------------------------------------------------------------

def test_create_list_rename_delete(hub):
    s = hub.create()
    assert s["title"] == "New chat" and s["turns"] == []
    assert [x["id"] for x in hub.list()] == [s["id"]]
    assert hub.rename(s["id"], "Recon")["title"] == "Recon"
    hub.delete(s["id"])
    assert hub.list() == []
    with pytest.raises(ns.NotFound):
        hub.get(s["id"])


def test_send_stores_both_turns_with_the_model_that_answered(hub):
    s = hub.create()
    out = send_and_wait(hub, s["id"], "nmap the lab subnet")
    assert out["route"] == "security" and out["model"] == "narwhal"
    got = hub.get(s["id"])
    user, reply = got["turns"]
    assert user["role"] == "user" and user["text"] == "nmap the lab subnet"
    assert reply["text"] == "Hello there." and reply["thinking"] == "thinking"
    assert reply["model"] == "narwhal" and reply["label"] == nr.label_for("security")
    assert reply["status"] == "ok" and reply["route"] == "security"
    assert got["title"] == "nmap the lab subnet" and got["last_route"] == "security"
    assert hub.fake.calls[0]["model"] == "narwhal"


def test_history_goes_back_to_the_model_and_routing_follows_the_session(hub):
    s = hub.create()
    send_and_wait(hub, s["id"], "Refactor this Python function please")
    send_and_wait(hub, s["id"], "and now?")
    second = hub.fake.calls[1]
    assert second["model"] == "forge"          # sticky
    assert [m["role"] for m in second["messages"] if m["role"] != "system"] == ["user", "assistant", "user"]


def test_route_can_be_picked_by_hand(hub):
    s = hub.create()
    out = send_and_wait(hub, s["id"], "nmap the subnet", route="code")
    assert out["model"] == "forge" and out["reason"] == "picked by hand"


def test_one_reply_at_a_time(tmp_path):
    gate = threading.Event()
    client = FakeClient(gate=gate)
    h = ns.Hub(path=tmp_path / "n.db", client=client)
    s = h.create()
    h.send(s["id"], "first")
    with pytest.raises(ns.Busy):
        h.send(s["id"], "second")
    gate.set()
    ns.wait_idle(h, s["id"])
    assert not h.running(s["id"])


def test_errors_are_kept_on_the_turn_and_not_sent_back(tmp_path):
    h = ns.Hub(path=tmp_path / "n.db", client=FakeClient(boom=RuntimeError("down")),
               error_message=lambda e: f"bad: {e}")
    s = h.create()
    send_and_wait(h, s["id"], "q")
    reply = h.get(s["id"])["turns"][1]
    assert reply["status"] == "error" and reply["error"] == "bad: down"
    assert h._history(s["id"], before=99) == [{"role": "user", "content": "q"}]


def test_stop_ends_the_reply_as_stopped(tmp_path):
    gate = threading.Event()
    h = ns.Hub(path=tmp_path / "n.db", client=FakeClient(gate=gate))
    s = h.create()
    h.send(s["id"], "long one")
    assert h.stop(s["id"])
    gate.set()
    ns.wait_idle(h, s["id"])
    reply = h.get(s["id"])["turns"][1]
    assert reply["status"] == "stopped" and reply["text"] == ""


def test_a_restart_marks_unfinished_replies_stopped(tmp_path):
    gate = threading.Event()
    h = ns.Hub(path=tmp_path / "n.db", client=FakeClient(gate=gate))
    s = h.create()
    h.send(s["id"], "q")
    again = ns.Hub(path=tmp_path / "n.db", client=FakeClient())
    assert again.get(s["id"])["turns"][1]["status"] == "stopped"
    gate.set()
    ns.wait_idle(h, s["id"])


def test_import_brings_the_old_phone_chat_in(hub):
    s = hub.import_turns("Phone chat", [
        {"role": "user", "text": "scan it"},
        {"role": "assistant", "text": "Done.", "thinking": "t", "seconds": 2.0},
        {"role": "assistant", "text": "", "failed": "oops"},
        {"role": "system", "text": "ignored"},
    ])
    assert [t["role"] for t in s["turns"]] == ["user", "assistant", "assistant"]
    assert s["turns"][1]["model"] == "narwhal" and s["turns"][2]["status"] == "error"
    assert s["last_route"] == "security"


# --- live watching -------------------------------------------------------

def collect(gen, until_type, limit=200):
    out = []
    for ev in gen:
        out.append(ev)
        if ev["type"] == until_type or len(out) >= limit:
            break
    return out


def test_a_second_device_joining_mid_reply_sees_all_of_it(tmp_path):
    gate = threading.Event()
    h = ns.Hub(path=tmp_path / "n.db", client=FakeClient(gate=gate))
    s = h.create()
    h.send(s["id"], "nmap it")                      # the Mac asks
    snap = h.get(s["id"])                           # the phone opens the session
    assert snap["running"] and snap["turns"][1]["thinking"] == "thinking"
    follow = h.follow(s["id"])                      # and follows from the live reply
    gate.set()
    ev = collect(follow, "done")
    types = [e["type"] for e in ev]
    assert types[0] == "hello" and ev[0]["running"]
    assert types[1:3] == ["user", "start"]
    assert "".join(e["text"] for e in ev if e["type"] == "text") == "Hello there."
    assert ev[-1]["turn"]["text"] == "Hello there." and ev[-1]["turn"]["model"] == "narwhal"


def test_follow_after_seq_only_sends_whats_new(hub):
    s = hub.create()
    send_and_wait(hub, s["id"], "one")
    seq = hub.get(s["id"])["seq"]
    follow = hub.follow(s["id"], after=seq, ping=0.05)
    assert next(follow)["type"] == "hello"
    assert next(follow)["type"] == "ping"           # nothing new
    hub.send(s["id"], "two")                        # sent from the other device
    ev = collect(follow, "done")
    assert ev[0]["type"] == "user" and ev[0]["turn"]["text"] == "two"
    assert all(e.get("seq", seq + 1) > seq for e in ev)


def test_follow_asks_for_a_resync_when_events_were_missed(hub):
    s = hub.create()
    send_and_wait(hub, s["id"], "one")
    send_and_wait(hub, s["id"], "two")              # the first reply's events are gone
    follow = hub.follow(s["id"], after=1, ping=0.05)
    next(follow)
    assert next(follow)["type"] == "resync"


def test_watch_reports_changes_to_any_session(hub):
    w = hub.watch(ping=0.05)
    assert next(w)["type"] == "hello"
    s = hub.create()
    ev = next(w)
    assert ev == {"type": "changed", "session": s["id"], "running": False}
    hub.delete(s["id"])
    seen = [next(w) for _ in range(2)]
    assert any(e.get("deleted") for e in seen)


# --- over HTTP -----------------------------------------------------------

def test_endpoints(tmp_path, monkeypatch):
    fastapi = pytest.importorskip("fastapi.testclient")
    import marina_server
    h = ns.Hub(path=tmp_path / "n.db", client=FakeClient())
    monkeypatch.setattr(marina_server, "_narwhal_hub", lambda: h)
    c = fastapi.TestClient(marina_server.app)
    sid = c.post("/narwhal/sessions", json={}).json()["id"]
    r = c.post(f"/narwhal/sessions/{sid}/messages", json={"text": "refactor this python function"})
    assert r.status_code == 200 and r.json()["model"] == "forge"
    ns.wait_idle(h, sid)
    assert c.get(f"/narwhal/sessions/{sid}").json()["turns"][1]["text"] == "Hello there."
    assert c.get("/narwhal/sessions").json()["sessions"][0]["id"] == sid
    assert c.get("/narwhal/sessions/nope").status_code == 404
    assert c.post(f"/narwhal/sessions/{sid}/messages", json={"text": " "}).status_code == 400
    assert c.get("/narwhal/route", params={"text": "nmap scan"}).json()["model"] == "narwhal"
    assert c.delete(f"/narwhal/sessions/{sid}").json() == {"ok": True}


# --- speed and context meter -------------------------------------------

def test_done_carries_llama_server_usage_and_speed():
    from process import narwhal
    last = NS(choices=[], usage=NS(prompt_tokens=1200, completion_tokens=80),
              model_extra={"timings": {"predicted_per_second": 27.34}})
    ev = list(narwhal.events(FakeClient([chunk("Hi"), last]), [{"role": "user", "content": "q"}], "narwhal"))
    done = ev[-1]
    assert done["prompt_tokens"] == 1200 and done["completion_tokens"] == 80 and done["tok_s"] == 27.3
    assert "estimated" not in done


def test_speed_is_estimated_without_usage():
    from process import narwhal
    ev = list(narwhal.events(FakeClient([chunk("x" * 400)]), [{"role": "user", "content": "q"}], "narwhal"))
    assert ev[-1]["completion_tokens"] == 100 and ev[-1]["estimated"] is True


def test_turns_keep_tokens_and_sessions_report_context(tmp_path):
    last = NS(choices=[], usage=NS(prompt_tokens=500, completion_tokens=20),
              model_extra={"timings": {"predicted_per_second": 30.0}})
    h = ns.Hub(path=tmp_path / "n.db", client=FakeClient([chunk("ok"), last]))
    s = h.create()
    send_and_wait(h, s["id"], "nmap")
    got = h.get(s["id"])
    reply = got["turns"][1]
    assert (reply["prompt_tokens"], reply["completion_tokens"], reply["tok_s"]) == (500, 20, 30.0)
    assert got["context"] == {"security": 131072, "code": 131072, "claude": 200000}


# --- notes (memory the owner writes) -------------------------------------

def test_notes_reach_the_model_on_both_routes(hub):
    hub.add_note("Lab network", "lab3 = 192.168.1.13, llama-swap in ct110 at 192.168.1.15:8080")
    hub.add_note("Off", "hidden", enabled=False)
    s = hub.create()
    send_and_wait(hub, s["id"], "nmap my lab")
    send_and_wait(hub, s["id"], "refactor this python function", route="code")
    for call in hub.fake.calls:
        system = call["messages"][0]
        assert system["role"] == "system"
        assert "## Lab network" in system["content"] and "192.168.1.15:8080" in system["content"]
        assert "hidden" not in system["content"]


def test_no_notes_no_system_prompt(hub):
    s = hub.create()
    send_and_wait(hub, s["id"], "hi")
    assert hub.fake.calls[0]["messages"][0]["role"] == "user"


def test_note_edit_toggle_delete_and_budget(hub):
    n = hub.add_note("Projects", "marina repo at ~/marina")
    assert hub.update_note(n["id"], body="narwhal repo at ~/narwhal")["body"] == "narwhal repo at ~/narwhal"
    assert hub.update_note(n["id"], enabled=False)["enabled"] is False
    assert hub.notes_block() == ""
    hub.update_note(n["id"], enabled=True)
    listing = hub.notes()
    assert listing["used_chars"] == len(hub.notes_block()) and listing["max_chars"] == ns.NOTES_MAX_CHARS
    hub.delete_note(n["id"])
    assert hub.notes()["notes"] == []
    with pytest.raises(ValueError):
        hub.add_note("", "")
    with pytest.raises(ValueError):
        hub.add_note("big", "x" * (ns.NOTE_MAX_CHARS + 1))


def test_notes_past_the_budget_are_left_out_whole(hub, monkeypatch):
    monkeypatch.setattr(ns, "NOTES_MAX_CHARS", 60)
    hub.add_note("A", "a" * 30)
    hub.add_note("B", "b" * 30)
    block = hub.notes_block()
    assert "## A" in block and "## B" not in block
    listing = hub.notes()["notes"]
    assert [(n["title"], n["included"]) for n in listing] == [("A", True), ("B", False)]


def test_watch_tells_devices_when_notes_change(hub):
    w = hub.watch(ping=0.05)
    next(w)
    hub.add_note("x", "y")
    assert next(w) == {"type": "notes"}


# --- the web server resumes streams on any worker thread ------------------

def _next_on_new_thread(gen):
    box = {}
    t = threading.Thread(target=lambda: box.setdefault("v", next(gen)))
    t.start()
    t.join(5)
    assert not t.is_alive(), "stream step hung"
    return box["v"]


def test_streams_can_be_resumed_from_other_threads_without_locking_others_out(hub):
    s = hub.create()
    send_and_wait(hub, s["id"], "one")
    follow = hub.follow(s["id"], ping=0.05)
    watch = hub.watch(ping=0.05)
    for gen in (follow, watch):
        for _ in range(3):          # hello, then pings
            _next_on_new_thread(gen)
    # With a lock left held by a finished worker thread, these would hang.
    done = threading.Event()
    threading.Thread(target=lambda: (hub.rename(s["id"], "x"), hub.delete(s["id"]), done.set())).start()
    assert done.wait(5), "a stream left the lock held"


def test_follow_ends_when_the_session_is_deleted(hub):
    s = hub.create()
    follow = hub.follow(s["id"], ping=0.05)
    next(follow)
    hub.delete(s["id"])
    assert list(follow) == [] or all(e["type"] == "ping" for e in follow)


def test_append_stores_a_claude_exchange_and_tells_followers(hub):
    s = hub.create()
    send_and_wait(hub, s["id"], "Refactor this Python function please")
    seq = hub.get(s["id"])["seq"]
    got = hub.append(s["id"], "now with Claude", {"text": "Done.", "thinking": "Read x.py", "model": "claude-opus-5-5",
                                                  "label": "Claude · Opus", "seconds": 12.5, "completion_tokens": 40,
                                                  "status": "weird", "tok_s": "x"})
    user, reply = got["turns"][2:]
    assert user["text"] == "now with Claude" and reply["route"] == "claude" and reply["text"] == "Done."
    assert reply["label"] == "Claude · Opus" and reply["status"] == "ok" and reply["tok_s"] is None
    assert got["last_route"] == "code"           # Auto still sticks to lab3's model
    ev = [e for e in hub.events[s["id"]] if e["seq"] > seq]
    assert [e["type"] for e in ev] == ["resync"]
    # Claude's reply is part of what lab3's models see next time.
    send_and_wait(hub, s["id"], "and now?")
    assert hub.fake.calls[-1]["messages"][-2]["content"] == "Done."
    with pytest.raises(ValueError):
        hub.append(s["id"], " ", {})
    with pytest.raises(ns.NotFound):
        hub.append("nope", "hi", {})


# --- Claude Code on lab3 -------------------------------------------------

def claude_hub(hub, monkeypatch, events=None):
    calls = []

    def fake(prompt, session, mode, model, system, cancel=None, effort=""):
        calls.append({"prompt": prompt, "session": session, "mode": mode, "model": model, "system": system,
                      "effort": effort})
        yield {"type": "session", "id": "cs-1", "model": "claude-opus-5-5"}
        yield from events or [{"type": "think", "text": "\n▸ Read  ~/x.py\n"}, {"type": "text", "text": "Fixed it."},
                              {"type": "done", "seconds": 9.5, "completion_tokens": 50, "prompt_tokens": 900}]
    monkeypatch.setattr(hub, "claude_ok", lambda: True)
    monkeypatch.setattr(hub, "claude_events", fake)
    return calls


def test_claude_is_picked_by_hand_and_streams_like_any_model(hub, monkeypatch):
    calls = claude_hub(hub, monkeypatch)
    s = hub.create()
    send_and_wait(hub, s["id"], "Refactor this Python function please")
    out = send_and_wait(hub, s["id"], "now you, Claude", route="claude")
    assert out["route"] == "claude" and out["reason"] == "picked by hand"
    reply = hub.get(s["id"])["turns"][-1]
    assert reply["text"] == "Fixed it." and "▸ Read" in reply["thinking"] and reply["status"] == "ok"
    assert reply["label"] == "Claude · Opus" and reply["model"] == "claude-opus-5-5"
    assert reply["completion_tokens"] == 50 and reply["seconds"] == 9.5
    # Its first turn hears what came before; it isn't sent to llama-swap.
    assert calls[0]["prompt"].startswith("Earlier in this chat") and "Refactor this Python" in calls[0]["prompt"]
    assert calls[0]["session"] == "" and calls[0]["mode"] == "acceptEdits" and len(hub.fake.calls) == 1
    # The next Claude turn continues its session, with the mode and model asked for.
    send_and_wait(hub, s["id"], "and run the tests", route="claude")
    hub_send = calls[1]
    assert hub_send["session"] == "cs-1" and hub_send["prompt"] == "and run the tests"
    assert "claude_session" not in hub.get(s["id"])


def test_claude_mode_and_model_reach_it(hub, monkeypatch):
    calls = claude_hub(hub, monkeypatch)
    s = hub.create()
    hub.send(s["id"], "plan it", "claude", "plan", "sonnet")
    ns.wait_idle(hub, s["id"])
    assert calls[0]["mode"] == "plan" and calls[0]["model"] == "sonnet"


def test_claude_effort_reaches_it_and_plan_usage_is_kept(hub, monkeypatch):
    usage = {"type": "usage", "at": 100, "status": "allowed",
             "windows": {"five_hour": {"used": 0.61, "resets": 200, "status": "allowed"}}}
    calls = claude_hub(hub, monkeypatch, [usage, {"type": "text", "text": "ok"}, {"type": "done", "seconds": 1}])
    s = hub.create()
    assert hub.claude_usage() is None
    hub.send(s["id"], "think hard", "claude", None, None, "max")
    ns.wait_idle(hub, s["id"])
    assert calls[0]["effort"] == "max"
    assert "can't reach the user's Mac" in calls[0]["system"]
    assert hub.claude_usage()["windows"]["five_hour"]["used"] == 0.61
    assert hub.get(s["id"])["turns"][-1]["text"] == "ok"
    # An older report (from the Mac, say) doesn't replace a newer one.
    hub.set_claude_usage({"at": 50, "windows": {"five_hour": {"used": 0.1}}})
    assert hub.claude_usage()["at"] == 100
    hub.set_claude_usage({"at": 150, "windows": {"five_hour": {"used": 0.7}}})
    assert hub.claude_usage()["windows"]["five_hour"]["used"] == 0.7


def test_claude_stream_reports_effort_and_plan_usage():
    import io
    from process import narwhal_claude as nc
    out = "\n".join(json.dumps(e) for e in [
        {"type": "rate_limit_event", "rate_limit_info": {"status": "allowed", "unifiedWindows": {
            "five_hour": {"utilization": 0.61, "resetsAt": 1795869600, "status": "allowed"},
            "seven_day": {"utilization": 0.33, "resetsAt": 1795986000, "status": "allowed"}}}},
        {"type": "result", "subtype": "success", "is_error": False, "usage": {}}]) + "\n"
    seen = {}

    class P:
        def __init__(self, args, **kw):
            seen["args"] = args
            self.stdin, self.stdout, self.stderr, self.returncode = io.StringIO(), io.StringIO(out), io.StringIO(), 0
        def wait(self, *a):
            return 0
    evs = list(nc.events("hi", effort="xhigh", popen=P))
    assert seen["args"][seen["args"].index("--effort") + 1] == "xhigh"
    u = [e for e in evs if e["type"] == "usage"][0]
    assert u["windows"]["seven_day"] == {"used": 0.33, "resets": 1795986000, "status": "allowed"}
    assert evs[-1]["type"] == "done"
    list(nc.events("hi", effort="bogus", popen=P))
    assert "--effort" not in seen["args"]


def test_claude_needs_setting_up_first(hub):
    s = hub.create()
    if not hub.claude_ok():
        with pytest.raises(ValueError):
            hub.send(s["id"], "hi", "claude")


def test_one_claude_run_at_a_time(hub, monkeypatch):
    from process import narwhal_claude
    claude_hub(hub, monkeypatch)
    s = hub.create()
    narwhal_claude.LOCK.acquire()
    try:
        send_and_wait(hub, s["id"], "hi", route="claude")
    finally:
        narwhal_claude.LOCK.release()
    reply = hub.get(s["id"])["turns"][-1]
    assert reply["status"] == "error" and "another chat" in reply["error"]


def test_claude_stream_json_becomes_narwhal_events():
    import io, json as j
    from process import narwhal_claude as nc
    out = [
        {"type": "system", "subtype": "init", "session_id": "abc", "model": "claude-opus-5-5"},
        {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Looking."}}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "1 failed"}]}},
        {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}},
        {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Fixed."}}},
        {"type": "result", "subtype": "success", "is_error": False, "duration_ms": 4200, "session_id": "abc",
         "usage": {"input_tokens": 10, "cache_read_input_tokens": 90, "output_tokens": 30},
         "permission_denials": [{"tool_name": "Bash"}]},
    ]

    class P:
        def __init__(self, args, **kw):
            self.args = args
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("".join(j.dumps(x) + "\n" for x in out))
            self.stderr = io.StringIO("")
            self.returncode = 0
        def wait(self, *a): return 0
    seen = {}
    def popen(args, **kw):
        seen["args"] = args
        return P(args, **kw)
    evs = list(nc.events("hi", session="abc", mode="bypassPermissions", model="opus", popen=popen))
    assert seen["args"][:6] == nc.CMD and "--resume" in seen["args"] and "bypassPermissions" in seen["args"]
    text = "".join(e["text"] for e in evs if e["type"] == "text")
    think = "".join(e["text"] for e in evs if e["type"] == "think")
    assert text.startswith("Looking.\n\nFixed.") and "wasn't allowed to use Bash" in text
    assert "▸ Bash  pytest -q" in think and "✗ 1 failed" in think
    assert evs[0] == {"type": "session", "id": "abc", "model": "claude-opus-5-5"}
    assert evs[-1] == {"type": "done", "seconds": 4.2, "completion_tokens": 30, "prompt_tokens": 100}


def test_claude_not_signed_in_says_how_to_fix_it():
    import io, json as j
    from process import narwhal_claude as nc
    res = {"type": "result", "subtype": "success", "is_error": True, "result": "Failed to authenticate", "duration_ms": 80}

    class P:
        def __init__(self, *a, **kw):
            self.stdin, self.stdout, self.stderr, self.returncode = io.StringIO(), io.StringIO(j.dumps(res) + "\n"), io.StringIO(""), 0
        def wait(self, *a): return 0
    evs = list(nc.events("hi", popen=P))
    assert evs[-1]["type"] == "error" and "auth login" in evs[-1]["message"]


# --- Quick and web search --------------------------------------------------

def tool_chunk(index, id=None, name=None, args=""):
    tc = NS(index=index, id=id, function=NS(name=name, arguments=args))
    return NS(choices=[NS(delta=NS(content=None, reasoning_content=None, tool_calls=[tc], model_extra={}))])


class ScriptClient(FakeClient):
    """Answers each call with the next script entry (a list of chunks)."""

    def __init__(self, script):
        super().__init__()
        self.script = list(script)

    def create(self, **kw):
        self.calls.append(kw)
        chunks = self.script.pop(0)
        return iter(chunks)


def test_quick_asks_the_model_not_to_think_and_sends_no_tools(hub):
    s = hub.create()
    hub.send(s["id"], "what's a /24?", "security", think="quick")
    ns.wait_idle(hub, s["id"])
    call = hub.fake.calls[0]
    assert call["extra_body"] == {"chat_template_kwargs": {"enable_thinking": False}}
    assert "tools" not in call
    # Think (the default) leaves it alone.
    send_and_wait(hub, s["id"], "and a /16?", "security")
    assert "extra_body" not in hub.fake.calls[1]


def test_web_search_runs_the_tool_and_answers_with_it(tmp_path, monkeypatch):
    client = ScriptClient([
        [chunk(reasoning="I should look it up."), tool_chunk(0, "c1", "web_search", '{"query": "lat'),
         tool_chunk(0, None, None, 'est nmap version"}')],
        [chunk("Nmap 7.97 is the latest "), chunk("(nmap.org).")],
    ])
    h = ns.Hub(path=tmp_path / "n.db", client=lambda: client, error_message=str)
    ran = []

    def fake_tool(name, args):
        ran.append((name, json.loads(args)))
        return "▸ Search  latest nmap version", "[1] Nmap 7.97 released\nhttps://nmap.org\n..."
    monkeypatch.setattr(h, "run_tool", fake_tool)
    s = h.create()
    h.send(s["id"], "what's the latest nmap?", "security", web=True)
    ns.wait_idle(h, s["id"])
    assert ran == [("web_search", {"query": "latest nmap version"})]
    first, second = client.calls
    assert first["tools"][0]["function"]["name"] == "web_search"
    assert "search the web" in first["messages"][0]["content"]
    # The second call carries the tool call and its result.
    assert second["messages"][-2]["tool_calls"][0]["function"]["name"] == "web_search"
    assert second["messages"][-1] == {"role": "tool", "tool_call_id": "c1",
                                      "content": "[1] Nmap 7.97 released\nhttps://nmap.org\n..."}
    turn = h.get(s["id"])["turns"][-1]
    assert turn["text"] == "Nmap 7.97 is the latest (nmap.org)." and turn["status"] == "ok"
    assert "▸ Search  latest nmap version" in turn["thinking"]


def test_web_search_stops_offering_tools_after_the_last_round():
    from process import narwhal
    loop = [tool_chunk(0, "c", "web_search", '{"query": "x"}')]
    client = ScriptClient([loop, loop, [chunk("ok")]])
    evs = list(narwhal.events(client, [{"role": "user", "content": "hi"}], "m",
                              tools=[{"type": "function"}], run_tool=lambda n, a: ("▸ Search  x", "r"),
                              max_rounds=2))
    assert "tools" in client.calls[1] and "tools" not in client.calls[2]
    assert evs[-1]["type"] == "done"


def test_search_tools_read_searxng_and_refuse_private_pages():
    import io
    from process import narwhal_search as s

    class R(io.BytesIO):
        headers = {"Content-Type": "text/html"}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    data = json.dumps({"results": [{"title": "A", "url": "https://a.example", "content": "first  hit"},
                                   {"title": "A again", "url": "https://a.example"},
                                   {"title": "B", "url": "https://b.example", "content": "second"}]}).encode()
    hits = s.search("q", opener=lambda req, timeout: R(data))
    assert [h["url"] for h in hits] == ["https://a.example", "https://b.example"] and hits[0]["content"] == "first hit"
    page = b"<html><head><title>t</title></head><body><script>x()</script><p>Hello &amp; welcome</p></body></html>"
    assert s.open_page("https://a.example", opener=lambda req, timeout: R(page), public=lambda h: True) == "Hello & welcome"
    assert "isn't on the public internet" in s.open_page("http://192.168.1.15:8080/", public=s._public)
    assert "Only http" in s.open_page("file:///etc/passwd")
    step, out = s.run("web_search", "not json")
    assert out == "No query given."


def test_profile_is_kept_and_checked(hub):
    assert hub.profile() == {"name": "", "color": "#3ed2d3", "avatar": ""}
    hub.set_profile(name="  Jacob   M ", color="#a594ff")
    p = hub.profile()
    assert p["name"] == "Jacob M" and p["color"] == "#a594ff"
    hub.set_profile(avatar="data:image/png;base64,iVBORw0KGgo=")
    assert hub.profile()["avatar"].startswith("data:image/png") and hub.profile()["name"] == "Jacob M"
    for bad in ({"color": "red"}, {"avatar": "javascript:alert(1)"}, {"avatar": "data:image/svg+xml;base64,PHN2Zz4="}):
        with pytest.raises(ValueError):
            hub.set_profile(**bad)
    hub.set_profile(avatar="")
    assert hub.profile()["avatar"] == ""


# --- working on the Mac ------------------------------------------------------

def mac_answerer(h, answer):
    """Plays the Mac app: answers every mac_tool request from the watch stream."""
    seen = []
    stop = threading.Event()

    def loop():
        for ev in h.watch(ping=0.1, until=stop.is_set):
            if ev.get("type") == "mac_tool":
                seen.append(ev)
                h.tool_result(ev["id"], answer(ev))
    threading.Thread(target=loop, daemon=True).start()
    return seen, stop


def test_mac_tools_go_to_the_mac_app_and_back(tmp_path):
    client = ScriptClient([
        [tool_chunk(0, "r1", "read_file", '{"path": "~/narwhal/app/src/main.rs"}')],
        [chunk("It starts the webviews.")],
    ])
    h = ns.Hub(path=tmp_path / "n.db", client=lambda: client, error_message=str)
    seen, stop = mac_answerer(h, lambda ev: "fn main() { start() }")
    s = h.create()
    time.sleep(0.2)
    h.send(s["id"], "what does main.rs do?", "code", mac=True)
    ns.wait_idle(h, s["id"])
    stop.set()
    assert seen[0]["name"] == "read_file" and seen[0]["args"] == {"path": "~/narwhal/app/src/main.rs"}
    assert seen[0]["session"] == s["id"]
    first, second = client.calls
    assert {t["function"]["name"] for t in first["tools"]} >= {"read_file", "run_command"}
    assert "user's Mac" in first["messages"][0]["content"]
    assert second["messages"][-1]["content"] == "fn main() { start() }"
    turn = h.get(s["id"])["turns"][-1]
    assert "▸ Read  ~/narwhal/app/src/main.rs" in turn["thinking"] and turn["text"] == "It starts the webviews."


def test_mac_tools_only_when_asked_and_denials_are_marked(tmp_path, hub):
    s = hub.create()
    send_and_wait(hub, s["id"], "hello", "security")
    assert "tools" not in hub.fake.calls[0]
    client = ScriptClient([[tool_chunk(0, "w", "run_command", '{"command": "rm -rf ~/x"}')], [chunk("OK, I won't.")]])
    h = ns.Hub(path=tmp_path / "m.db", client=lambda: client, error_message=str)
    seen, stop = mac_answerer(h, lambda ev: "Denied: the user said no.")
    s2 = h.create()
    time.sleep(0.2)
    h.send(s2["id"], "clean up", "security", mac=True)
    ns.wait_idle(h, s2["id"])
    stop.set()
    assert "▸ Run  rm -rf ~/x  ✗ not allowed" in h.get(s2["id"])["turns"][-1]["thinking"]


def test_mac_tool_gives_up_when_the_mac_is_away(tmp_path, monkeypatch):
    monkeypatch.setattr(ns, "MAC_TOOL_WAIT", 0.3)
    client = ScriptClient([[tool_chunk(0, "l", "list_dir", '{"path": "~"}')], [chunk("The Mac isn't answering.")]])
    h = ns.Hub(path=tmp_path / "a.db", client=lambda: client, error_message=str)
    s = h.create()
    h.send(s["id"], "what's in my home folder?", "security", mac=True)
    ns.wait_idle(h, s["id"])
    assert "didn't answer" in client.calls[1]["messages"][-1]["content"]
    with pytest.raises(ns.NotFound):
        h.tool_result("gone", "late")
