from process import mood


def test_rudeness_cools_her_and_time_brings_her_back():
    usual = mood.current(now=1000.0)["warmth"]
    after = mood.feel("shut up you're useless", now=1000.0)
    assert after["warmth"] < usual
    assert "put out" in mood.describe(after) or "cool" in mood.describe(after)
    much_later = mood.current(now=1000.0 + 12 * 3600)
    assert abs(much_later["warmth"] - usual) < 0.02


def test_she_can_be_short_but_there_is_a_floor():
    for i in range(10):
        got = mood.feel("i hate you, shut up", now=1000.0 + i)
    assert got["warmth"] == mood.FLOOR["warmth"]
    assert "not unkind" in mood.describe(got)


def test_an_apology_helps():
    cold = mood.feel("you're so annoying", now=1.0)
    warmer = mood.feel("sorry, didn't mean that", now=2.0)
    assert warmer["warmth"] > cold["warmth"]


def test_her_usual_self_needs_no_note(monkeypatch):
    monkeypatch.setattr(mood, "setting", lambda s, k, d=None: d)
    assert mood.note("what are you up to") == ""
    assert mood.face() is None
    assert "mood right now" in mood.note("shut up")
    mood.feel("shut up, you suck")
    assert mood.face()["name"] == "angry"


def test_mood_survives_a_restart():
    from process import state
    mood.feel("guess what!! i passed", now=50.0)
    saved = mood.current(now=50.0)
    state.forget()
    assert mood.current(now=50.0) == saved


def test_her_voice_follows_her_energy(monkeypatch):
    monkeypatch.setattr(mood, "setting", lambda s, k, d=None: d)
    assert mood.voice_speed() == 1.0
    for _ in range(4):
        mood.feel("guess what!! we won, finally, let's gooo")
    assert 1.0 < mood.voice_speed() <= 1.06
