"""Time gaps, recall, the note cap, storyline arcs, examples, ratings,
and trying her out without it sticking."""
import json
from datetime import date, datetime, timedelta

import pytest

from process import care, gap, ratings, state
from process.llm_funcs import llm_scr
from process.memory import extract, followup, persona, recall, store


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MEMORY_FILE", tmp_path / "memory.json")
    monkeypatch.setattr(store.shared, "enabled", lambda: False)
    monkeypatch.setattr(followup, "setting", lambda s, k, d=None: d)
    monkeypatch.setattr(recall, "setting", lambda s, k, d=None: d)
    recall.reset()
    return store


# -- time

def at(when, role="assistant"):
    return {"role": role, "content": "x", "at": when.isoformat()}


def test_a_long_gap_is_noticed_and_a_short_one_is_not():
    now = datetime(2026, 11, 13, 18, 0)
    assert gap.note([at(now - timedelta(minutes=40))], now) == ""
    note = gap.note([at(now - timedelta(days=4))], now)
    assert "4 days ago" in note and "first you've heard from them today" in note
    assert "a while for you two" in note
    assert gap.note([{"role": "user", "content": "old, no time"}], now) == ""


def test_first_message_of_the_day():
    now = datetime(2026, 11, 13, 9, 0)
    note = gap.note([at(datetime(2026, 11, 12, 23, 30))], now)
    assert "about 10 hours ago" in note and "today" in note


def test_times_are_saved_but_never_sent_to_the_model(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_scr, "_history_file", lambda: str(tmp_path / "h.json"))
    monkeypatch.setattr(llm_scr, "_shared_history", lambda: False)
    monkeypatch.setattr(llm_scr, "_remember", lambda: False)
    llm_scr.append_history([{"role": "user", "content": "hi"},
                            {"role": "assistant", "content": "hey"}])
    saved = llm_scr.load_local_history()
    assert all(m.get("at") for m in saved)
    assert llm_scr._bare(saved) == [{"role": "user", "content": "hi"},
                                    {"role": "assistant", "content": "hey"}]


# -- the note cap

def test_only_the_most_important_notes_ride_along(monkeypatch):
    said = lambda text: (lambda *a, **k: f"<{text}>")
    monkeypatch.setattr(llm_scr, "_recall", lambda: True)
    monkeypatch.setattr(llm_scr.config, "setting", lambda s, k, d=None: d)
    monkeypatch.setattr(llm_scr.care, "note", lambda h, t: "")
    monkeypatch.setattr(llm_scr.mood, "note", said("mood"))
    monkeypatch.setattr(llm_scr.followup, "note", said("ask"))
    monkeypatch.setattr(llm_scr.lore, "note", said("lore"))
    monkeypatch.setattr(llm_scr.gap, "note", said("gap"))
    monkeypatch.setattr(llm_scr.recall, "note", said("recall"))
    monkeypatch.setattr(llm_scr.fresh, "steer", said("steer"))
    monkeypatch.setattr(llm_scr.fresh, "note", said("fresh"))
    monkeypatch.setattr(llm_scr.persona, "as_prompt_block", said("life"))
    assert llm_scr.turn_notes([], "hello there") == "<ask><lore>"
    monkeypatch.setattr(llm_scr.followup, "note", lambda **k: "")
    monkeypatch.setattr(llm_scr.lore, "note", lambda h, t: "")
    assert llm_scr.turn_notes([], "hello there") == "<gap><recall>"
    # When they are low, the lively ones go and the gentle one comes last.
    monkeypatch.setattr(llm_scr.care, "note", lambda h, t: "<gentle>")
    assert llm_scr.turn_notes([], "hello there") == "<fresh><gentle>"


# -- follow-ups

def test_a_rough_day_is_asked_about_differently(memory):
    raw = '[{"event": "The user has an interview", "on": "2026-10-19", "rough": true}]'
    got = extract._parse(raw, date(2026, 10, 12))
    assert got == [{"event": "The user has an interview", "on": "2026-10-19~"}]
    memory.add(got[0]["event"], source=store.EVENT, due=got[0]["on"])
    assert "whether it has happened yet" in followup.note(date(2026, 10, 19))


def test_she_does_not_ask_once_they_have_told_her(memory):
    memory.add("The user has their driving test", source=store.EVENT, due="2026-10-13")
    assert followup.note(date(2026, 10, 14), "so the driving test went badly") == ""
    assert memory.events() == []
    assert followup.note(date(2026, 10, 14)) == ""


def test_what_she_has_asked_is_kept_across_a_restart(memory):
    memory.add("The user has their driving test", source=store.EVENT, due="2026-10-13")
    assert followup.note(date(2026, 10, 13))
    assert followup.note(date(2026, 10, 13))
    state.forget()                                   # as after a restart
    assert followup.note(date(2026, 10, 13)) == ""


def test_what_the_model_made_of_them_and_of_her(memory):
    raw = ('[{"feeling": "low"}, {"self": "You think season two is the best one"},'
           ' {"self": "The user likes tea"}, {"feeling": "bored"}]')
    assert extract._parse(raw) == [{"feeling": "low"},
                                   {"self": "You think season two is the best one"}]
    assert care.level([], "nothing much") == ""
    care.heard("low", now=100.0)
    assert care._heard(now=200.0) == "low"
    assert care._heard(now=100.0 + care.HEARD_FOR + 1) == ""


# -- older episodes

def test_an_older_episode_comes_back_with_its_subject(memory):
    memory.add("They told you about the robot arm they are building for the science "
               "fair and the servo that kept burning out.", source=store.EPISODE)
    for i in range(store.EPISODES_IN_PROMPT):
        memory.add(f"You and they chatted about film number {i} for a while.",
                   source=store.EPISODE)
    note = recall.note("the servo on my robot arm died again")
    assert "science" in note and "Don't retell" in note
    assert recall.note("the servo on my robot arm died yet again") == ""   # resting
    assert recall.note("what should i have for dinner tonight") == ""


# -- her own life

def test_a_storyline_moves_on_each_day(monkeypatch):
    monkeypatch.setattr(persona, "threads", lambda: [["starts", "middle", "ends"]])
    monkeypatch.setattr(persona, "DAYS_EACH", 3)
    start = date.fromordinal((date(2026, 11, 13).toordinal() // 3) * 3)
    got = [persona.current_thread(start + timedelta(days=d)) for d in range(3)]
    assert got == ["starts", "middle", "ends"]


def test_examples_show_her_voice(monkeypatch):
    values = {("persona", "examples"): [{"them": "i passed", "you": "wait, actually? ok, proud of you."}]}
    monkeypatch.setattr(persona, "setting", lambda s, k, d=None: values.get((s, k), d))
    block = persona.examples_block()
    assert "Them: i passed\nYou: wait, actually?" in block and "never reuse" in block


def test_her_own_notes_never_crowd_out_what_she_knows_about_them(memory, monkeypatch):
    monkeypatch.setattr(store, "MAX_SELF", 2)
    memory.add("The user has a cat named Mochi")
    for thing in ("you love the first opening", "you never finished the retrospective",
                  "you think tabs beat spaces"):
        memory.add(thing.capitalize(), source=store.SELF)
    texts = [f["text"] for f in memory.local_facts()]
    assert len(texts) == 3 and any("Mochi" in t for t in texts)
    assert not any("first opening" in t for t in texts)


# -- ratings, keeping, rehearsal

def test_a_rating_is_saved_with_the_exchange(tmp_path, monkeypatch):
    monkeypatch.setattr(ratings, "_path", lambda: tmp_path / "ratings.jsonl")
    history = [{"role": "user", "content": "guess what"},
               {"role": "assistant", "content": "what did you break."}]
    assert ratings.rate(True, history, "marina")["them"] == "guess what"
    ratings.rate(False, history, "marina", "too flat")
    assert ratings.counts() == {"good": 1, "bad": 1}
    last = json.loads((tmp_path / "ratings.jsonl").read_text().splitlines()[-1])
    assert last["her"] == "what did you break." and last["note"] == "too flat"
    assert ratings.rate(True, []) is None


def test_keeping_a_fact_for_good(memory):
    fact = memory.add("The user owns a red bicycle")
    assert memory.pin(fact["id"])
    assert memory.local_facts()[0]["source"] == "told"


def test_a_rehearsal_leaves_nothing_behind(memory):
    from process import mood
    before = mood.current(now=10.0)
    with state.rehearsal():
        mood.feel("shut up you're useless", now=10.0)
        assert memory.add("The user owns a red bicycle") is None
    assert mood.current(now=10.0) == before
    assert memory.local_facts() == []


def test_a_text_on_the_day_and_only_once(memory, monkeypatch):
    from process import telegram
    monkeypatch.setattr(telegram.idle, "muted", lambda: False)
    monkeypatch.setattr(telegram.idle, "in_quiet_hours", lambda: False)
    monkeypatch.setattr(telegram, "setting", lambda s, k, d=None: d)
    memory.add("The user has their driving test", source=store.EVENT, due="2026-10-13")
    assert telegram._event_today(datetime(2026, 10, 13, 7, 0)) is None      # too early
    assert telegram._event_today(datetime(2026, 10, 13, 9, 0))["text"].endswith("driving test")
    assert telegram._event_today(datetime(2026, 10, 13, 9, 5)) is None
    assert telegram._event_today(datetime(2026, 10, 14, 9, 0)) is None
