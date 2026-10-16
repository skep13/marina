"""She notices coming back after a break and long stretches in one app, once
each, and ignores her own window and the Finder."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process.notice import Watcher

MIN = 60


def test_coming_back_after_a_break_is_noticed_once():
    w = Watcher(away=20 * MIN, focus=120 * MIN)
    assert w.update(0, 5, "Safari") is None
    assert w.update(30 * MIN, 25 * MIN, "Safari") is None   # still away
    back = w.update(31 * MIN, 1, "Safari")
    assert back and "about 25 minutes" in back
    assert w.update(32 * MIN, 1, "Safari") is None


def test_a_long_stretch_in_one_app_is_noticed_once():
    w = Watcher(away=20 * MIN, focus=120 * MIN)
    assert w.update(0, 1, "Xcode") is None
    assert w.update(60 * MIN, 1, "Xcode") is None
    assert w.update(60 * MIN + 1, 1, "Marina") is None      # her window doesn't count
    said = w.update(121 * MIN, 1, "Xcode")
    assert said and "Xcode" in said
    assert w.update(200 * MIN, 1, "Xcode") is None


def test_switching_apps_or_a_break_restarts_the_stretch():
    w = Watcher(away=20 * MIN, focus=120 * MIN)
    w.update(0, 1, "Xcode")
    w.update(100 * MIN, 1, "Slack")
    assert w.update(150 * MIN, 1, "Slack") is None
    w.update(160 * MIN, 30 * MIN, "Slack")                   # walked off
    w.update(161 * MIN, 1, "Slack")                          # back: says hi
    assert w.update(250 * MIN, 1, "Slack") is None
