import time

from process import push


def test_phone_counts_only_while_in_front_and_recent():
    push.phone_presence(False)
    assert not push.phone_here()
    push.phone_presence(True)
    assert push.phone_here()
    assert not push.phone_here(now=time.time() + push.PHONE_STALE + 1)
    push.phone_presence(False)
    push.phone_polled()                     # a poll from the background
    assert not push.phone_here()


def test_desk_counts_while_a_stream_is_open_and_briefly_after():
    push.desk_stream(True)
    assert push.desk_here(now=time.time() + 3600)
    push.desk_stream(False)
    assert push.desk_here()
    assert not push.desk_here(now=time.time() + push.DESK_STALE + 1)


def test_send_does_nothing_when_off(monkeypatch):
    monkeypatch.setattr(push, "ENABLED", False)
    assert push.send("hi") is False
