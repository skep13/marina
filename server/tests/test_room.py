from process import room, state


def test_notes_build_a_diary_and_skip_pass(monkeypatch):
    store = {}
    monkeypatch.setattr(state, "get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(state, "put", lambda k, v: store.__setitem__(k, v) or v)
    assert room.note("PASS") is None
    room.note("The parser is done and tested.", "Build a tiny DB", "work", ["Arty"])
    assert len(room.diary()) == 1
    assert "handed in" in room.home_note("what were you up to in the room?")
    assert room.home_note("what's for dinner") == ""
    ctx = room.context()
    assert "Earlier in the room" in ctx and "Arty" in ctx
    assert "Keep straight whose life" not in ctx
