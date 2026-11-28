from process.tts_func.engine import spoken_fillers


def test_fillers_become_sounds_kokoro_says():
    assert spoken_fillers("mm-hm.") == "uh-huh."
    assert spoken_fillers("Mhm, sure") == "Uh-huh, sure"
    assert spoken_fillers("Mm-hmm. okay") == "Uh-huh. okay"
    assert spoken_fillers("mm. maybe") == "hmm. maybe"
    assert spoken_fillers("Mmm, that's good") == "Hmm, that's good"
    assert spoken_fillers("hm? hmmm") == "hmm? hmm"


def test_words_left_alone():
    assert spoken_fillers("Him and them, mum, hummus, summer, I'm") == "Him and them, mum, hummus, summer, I'm"
