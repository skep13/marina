from process.llm_funcs import fresh


def her(*texts):
    out = []
    for t in texts:
        out += [{"role": "user", "content": "hey"}, {"role": "assistant", "content": t}]
    return out


# What she was actually saying on lab3 when this was written.
STUCK = her(
    "oh wow it's saturday night and you're still awake! what are you doing on your phone at this hour??",
    "ugh that sucks lol. seven days until china and you're stuck working instead of traveling. at least it's saturday night though right?",
    "ugh that sucks lol. thirty two days and you're stuck working instead of chilling. at least china's coming eventually right?",
    "oh wow it's saturday night and you're still awake! what are you doing on your phone at this hour??",
    "oh wow it's saturday night and you're still awake! what are you doing on your phone at this hour??",
)


def test_names_the_opener_she_keeps_using():
    n = fresh.note(STUCK)
    assert "oh wow it's saturday" in n
    assert "ugh that sucks lol" in n
    assert "Start this one a different way" in n


def test_names_repeated_phrases_and_tics():
    assert any("stuck working instead" in p for p in fresh.repeated_phrases(fresh._recent(STUCK)))
    assert "oh wow" in fresh.tics(fresh._recent(STUCK))


def test_says_nothing_with_too_little_to_go_on():
    assert fresh.note(her("hi there!")) == ""
    assert fresh.note([]) == ""


def test_varied_replies_get_no_phrase_warnings():
    varied = her("Morning! Sleep okay?", "That bug sounds nasty. Which file is it in?",
                 "Ha, the cat wins again.")
    assert fresh.repeated_phrases(fresh._recent(varied)) == []
    assert fresh.tics(fresh._recent(varied)) == []


def test_reads_text_from_image_messages():
    msgs = her("first reply here ok", "second reply here ok")
    msgs.append({"role": "assistant", "content": [{"type": "text", "text": "third reply here ok"}]})
    assert "third reply here" in fresh.note(msgs)


CHINA = her(
    "not much lol still watching anime. how's your china trip prep going? still got thirty two days?",
    "ugh work killing you again lol. at least china's coming eventually though right? thirty two days.",
    "yeah i can tell. thirty two days until china and you're already running on empty.",
)


def test_names_a_subject_she_keeps_bringing_up():
    n = fresh.note(CHINA, "yeah its been a long week honestly")
    assert '"china"' in n and "leave that alone" in n


def test_a_subject_they_raise_is_fair_game():
    assert "china" not in fresh.topics(fresh._recent(CHINA), ["china", "trip"])
