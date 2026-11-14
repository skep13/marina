from process.llm_funcs import fresh


def chat(*hers):
    out = []
    for h in hers:
        out += [{"role": "user", "content": "mm"}, {"role": "assistant", "content": h}]
    return out


def test_after_only_reacting_she_is_asked_to_carry_it():
    history = chat("ha, classic.", "ugh, that's rough.", "*snorts* of course it did.")
    assert "carry it forward" in fresh.steer(history, "yeah")


def test_not_when_they_asked_her_something():
    history = chat("ha, classic.", "ugh, that's rough.", "of course it did.")
    assert fresh.steer(history, "what are you up to?") == ""


def test_a_recent_question_is_enough():
    history = chat("ha, classic.", "wait, which one? *tilts head*", "of course it did.")
    assert fresh.steer(history, "yeah") == ""


def test_question_after_question_is_reined_in():
    history = chat("oh nice. how did it go?", "and then what happened?")
    assert "no question" in fresh.steer(history, "it was fine")
