from process import call


def setup_function(_):
    call.end()


def test_off_by_default_leaves_replies_alone():
    assert not call.active()
    assert call.extra_for("hi", None) is None
    assert call.extra_for("hi", "\n\nx") == "\n\nx"


def test_on_a_call_replies_get_the_call_style():
    call.start()
    assert call.active()
    extra = call.extra_for("how are you", None)
    assert "voice call" in extra
    assert call.extra_for("hi", "\n\nnote").startswith("\n\nnote")


def test_unprompted_replies_keep_their_own_instruction():
    call.start()
    assert call.extra_for(None, "\n\nopener") == "\n\nopener"


def test_pick_up_says_hello_in_call_style():
    text = call.pick_up()
    assert "voice call" in text and "picked up" in text


def test_end_reports_length_and_turns_off():
    call.start()
    out = call.end()
    assert out["on"] is False and out["seconds"] >= 0
    assert not call.active()
    assert call.status() == {"on": False, "seconds": 0}
