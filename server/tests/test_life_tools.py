"""Lists, the morning brief, lab health, the iCloud calendar, projects and
the coding model staying loaded."""
from datetime import datetime

import pytest

from process.tools import calendar_source, lab_health, lists, workspace


@pytest.fixture
def mem(monkeypatch):
    store = {}
    from process import state
    monkeypatch.setattr(state, "get", lambda k, d=None: store.get(k, d))
    monkeypatch.setattr(state, "put", lambda k, v: store.__setitem__(k, v))
    return store


@pytest.fixture
def list_file(tmp_path, monkeypatch):
    monkeypatch.setattr(lists, "FILE", tmp_path / "lists.json")


# ---- lists -------------------------------------------------------------------

def test_lists_add_read_remove(list_file):
    assert "Added to the shopping list: milk, eggs" in lists.add_to_list("groceries", ["milk", "eggs"])
    assert "already" in lists.add_to_list("my shopping list", "Milk")
    assert "- milk" in lists.read_list("shopping")
    assert "shopping: 2 things" in lists.read_list("")
    assert "Took off the shopping list: milk" in lists.remove_from_list("shopping", ["the milk"])
    assert "The list is empty now" in lists.remove_from_list("shopping", "eggs")
    assert "They have no lists yet" in lists.read_list()


def test_list_names_and_splitting(list_file):
    lists.add_to_list("To do", "fix the bike, call mum and book the dentist")
    assert lists.read_list("todo").count("\n- ") == 3
    assert "3 on the to-do list (oldest: fix the bike)" == lists.brief()
    assert "Cleared the to-do list (3 things)." == lists.clear_list("tasks")


# ---- morning brief -----------------------------------------------------------

def test_brief_once_a_day(mem, monkeypatch):
    from process import brief
    monkeypatch.setattr(brief, "gather", lambda: ["Weather: sunny, 12°C."])
    monkeypatch.setattr(brief, "_on", lambda part: True)
    morning = datetime(2026, 11, 23, 8, 30)
    first = brief.note(morning)
    assert "first time they've talked to you today" in first and "sunny" in first
    assert "morning" in first
    assert brief.note(datetime(2026, 11, 23, 13, 0)) == ""
    # 1am still belongs to the day before; 5am is a new day.
    assert brief.note(datetime(2026, 11, 24, 1, 0)) == ""
    assert brief.note(datetime(2026, 11, 24, 5, 0)) != ""


def test_brief_skips_empty(mem, monkeypatch):
    from process import brief
    monkeypatch.setattr(brief, "gather", lambda: [])
    monkeypatch.setattr(brief, "_on", lambda part: True)
    assert brief.note(datetime(2026, 11, 25, 9, 0)) == ""


# ---- lab health --------------------------------------------------------------

def test_lab_problems_keyed_without_numbers():
    a = lab_health._key("lab3's model disk is 93% full, 15 GB left")
    b = lab_health._key("lab3's model disk is 94% full, 13 GB left")
    assert a == b


def test_lab_watch_tells_once_then_clears(mem, monkeypatch):
    said = []
    reports = iter([
        {"problems": ["lab1 is off or unreachable"]},
        {"problems": ["lab1 is off or unreachable"]},
        {"problems": ["lab1 is off or unreachable"]},
        {"problems": []},
    ])
    monkeypatch.setattr(lab_health, "check", lambda: next(reports))
    monkeypatch.setattr(lab_health, "on_change", said.append)
    monkeypatch.setattr(lab_health, "CONFIRM", 2)

    class Stop(Exception):
        pass
    n = {"i": 0}

    def sleep(_):
        n["i"] += 1
        if n["i"] >= 4:
            raise Stop
    monkeypatch.setattr(lab_health.time, "sleep", sleep)
    with pytest.raises(Stop):
        lab_health._watch()
    assert len(said) == 2
    assert "lab1 is off" in said[0] and "cleared up" in said[1]


# ---- iCloud calendar ---------------------------------------------------------

ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Dentist\\, check-up
LOCATION:High St
DTSTART:20261124T093000Z
DTEND:20261124T100000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Mum's birthday
DTSTART;VALUE=DATE:20261125
DTEND;VALUE=DATE:20261126
END:VEVENT
END:VCALENDAR"""


def test_parse_icloud_events():
    events = calendar_source.parse_events(ICS, "Home")
    assert [e["title"] for e in events] == ["Dentist, check-up", "Mum's birthday"]
    assert events[0]["location"] == "High St" and not events[0]["all_day"]
    assert events[1]["all_day"] and events[1]["start"] == datetime(2026, 11, 25)


def test_calendar_needs_setup(monkeypatch):
    monkeypatch.setattr(calendar_source, "_mac_ready", lambda: False)
    monkeypatch.setattr(calendar_source, "icloud_ready", lambda: False)
    assert "isn't connected" in calendar_source.calendar()


# ---- projects and pushing ----------------------------------------------------

def test_push_only_through_git_push():
    for c in ["git push", "git push -u origin main", "cd x && git -C y push --force",
              "gh pr create --fill", "gh repo create foo --public"]:
        assert "git_push" in (workspace.refused(c) or ""), c
    for c in ["git status", "git commit -m 'push button'", "git pull", "gh pr list"]:
        assert workspace.refused(c) is None, c


def test_project_names_stay_in_projects():
    assert workspace._project_dir("room-of-ais") == f"{workspace.ROOT}/room-of-ais"
    assert workspace._project_dir("~/projects/app") == f"{workspace.ROOT}/app"
    for bad in ["../etc", "a/b", "", "x;rm -rf ~", ".hidden"]:
        with pytest.raises(ValueError):
            workspace._project_dir(bad)


def test_project_path_quoting_expands_home():
    assert workspace._qp("~/projects/app") == '"$HOME/projects/app"'


def test_every_push_is_asked(monkeypatch):
    from process.tools import registry
    monkeypatch.setattr(workspace, "push_question", lambda p, r: f"Let Marina push {p}?")
    q = registry.needs_ok("git_push", '{"project": "app"}', {"git_push"})
    assert q == "Let Marina push app?"


# ---- the coding model stays loaded -------------------------------------------

def test_route_sticks_after_work(monkeypatch):
    from process.llm_funcs import llm_scr
    route = {"model": "forge", "temperature": 0.3}
    sent = []
    monkeypatch.setattr(llm_scr, "chat_completion", lambda m, **kw: sent.append(kw))
    monkeypatch.setattr(llm_scr, "_sticky", {"route": None, "until": 0.0})
    monkeypatch.setattr(workspace, "available", lambda: False)
    llm_scr.get_reply_stream([], working=False, route=route)
    assert "_model" not in sent[-1]               # first round: her own model
    llm_scr.get_reply_stream([], working=True, route=route)
    assert sent[-1]["_model"] == "forge"
    assert llm_scr.sticky_route() is route
    llm_scr.get_reply_stream([], working=False, route=route)
    assert sent[-1]["_model"] == "forge"          # next message: no swap back
    llm_scr._sticky["until"] = 0
    assert llm_scr.sticky_route() is None
