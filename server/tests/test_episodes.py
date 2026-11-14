import pytest

from process.llm_funcs import llm_scr
from process.memory import episode, store


@pytest.fixture
def memory(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "MEMORY_FILE", tmp_path / "memory.json")
    monkeypatch.setattr(store.shared, "enabled", lambda: False)
    return store


def test_the_latest_episodes_are_in_her_prompt_oldest_first(memory):
    for i in range(7):
        memory.add(f"You and they talked about project number {i} for a while.",
                   source=store.EPISODE)
    block = memory.as_prompt_block()
    assert "number 0" not in block and "number 1" not in block
    assert block.index("number 2") < block.index("number 6")


def test_hearing_a_fact_again_does_not_reorder_the_prompt(memory):
    memory.add("The user has a cat named Mochi")
    memory.add("The user lives in Leeds")
    before = memory.as_prompt_block()
    assert memory.add("The user has a cat named Mochi") is None   # heard again
    assert memory.as_prompt_block() == before


def test_what_they_told_her_to_remember_is_never_pushed_out(memory, monkeypatch):
    monkeypatch.setattr(store, "MAX_FACTS", 3)
    memory.add("The user wants the jokes dropped when they are low", source="explicit")
    for thing in ("a red bicycle", "two pet snakes", "an old film camera", "a broken kettle"):
        memory.add(f"The user owns {thing}")
    texts = [f["text"] for f in memory.local_facts()]
    assert len(texts) == 3
    assert any("jokes dropped" in t for t in texts)
    assert not any("bicycle" in t for t in texts)


def test_a_transcript_says_who_said_what():
    text = episode._transcript([{"role": "user", "content": "we run a hack club now"},
                                {"role": "assistant", "content": "wait, since when?"}])
    assert text == "They: we run a hack club now\nMarina: wait, since when?"


def test_what_scrolls_out_of_her_window_becomes_an_episode(tmp_path, monkeypatch):
    kept = []
    monkeypatch.setattr(llm_scr, "_history_file", lambda: str(tmp_path / "h.json"))
    monkeypatch.setattr(llm_scr, "_remember", lambda: True)
    monkeypatch.setattr(llm_scr.episode, "remember_async", kept.append)
    turn = lambda i: [{"role": "user", "content": f"u{i}"},
                      {"role": "assistant", "content": f"a{i}"}]
    for i in range(llm_scr.SEND_WINDOW + 1):      # just past two windows' worth
        llm_scr.append_local(turn(i))
    assert len(kept) == 1
    assert len(kept[0]) == llm_scr.SEND_WINDOW
    assert kept[0][0]["content"] == "u0"
