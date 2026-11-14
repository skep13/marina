from process import care


def said(*texts):
    return [{"role": "user", "content": t} for t in texts]


def test_notices_someone_low():
    assert care.level([], "honestly i feel like shit today") == "low"
    assert care.level([], "im so tired of everything") == "low"
    assert care.level([], "what's the point") == "low"


def test_notices_a_crisis():
    assert care.level([], "i don't want to be here anymore") == "crisis"
    assert care.level([], "sometimes i think about killing myself") == "crisis"


def test_ordinary_talk_and_jokes_are_left_alone():
    assert care.level([], "my day was fine, the build finally passed") == ""
    assert care.level([], "what is the point of semicolons") == ""
    assert care.level([], "this bug makes me want to die lol") == ""


def test_she_stays_gentle_for_a_few_messages():
    history = said("i feel so alone", "yeah")
    assert care.level(history, "idk") == "low"
    history = said("i feel so alone", "yeah", "idk", "anyway")
    assert care.level(history, "did you see the new episode") == ""


def test_the_note_drops_the_snark_and_keeps_it_about_them(monkeypatch):
    monkeypatch.setattr(care, "setting", lambda s, k, d=None: d)
    note = care.note([], "i feel really low")
    assert "no teasing" in note and "your own past" in note
    assert "safe right now" not in note
    assert care.note([], "nice weather") == ""


def test_a_crisis_note_points_to_a_real_person(monkeypatch):
    lines = {("care", "crisis_line"): "Samaritans on 116 123"}
    monkeypatch.setattr(care, "setting", lambda s, k, d=None: lines.get((s, k), d))
    note = care.note([], "i want to die")
    assert "safe right now" in note and "Samaritans on 116 123" in note
    assert "keep talking" in note
