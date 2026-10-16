"""Things she notices about what they're doing on the Mac, to bring up:
coming back after a while away, or a long stretch in one app.

Off unless `idle.notice` is set, and only on a bridge running on macOS.
What she notices goes out through the same long poll as her other openers,
so mute, quiet hours and max_per_hour hold for it too. Nothing is recorded:
it keeps the current app and when they last touched the keyboard or mouse.
"""
import re
import subprocess
import sys
import time

from process.config import setting
from process.tools.context import frontmost_app

AWAY_MINUTES = 20        # this long without touching anything counts as away
FOCUS_MINUTES = 120      # this long in one app is worth a word

# Apps that aren't "what they're doing": her own window, the Finder, macOS.
_IGNORED = re.compile(r"^(Marina|Electron|Finder|loginwindow|Dock|SystemUIServer"
                      r"|ScreenSaverEngine|System Settings)$", re.I)


def enabled():
    return (sys.platform == "darwin" and bool(setting("idle", "notice", False))
            and bool(setting("idle", "enabled", True)))


def seconds_idle():
    """Seconds since they last used the keyboard, mouse or trackpad."""
    try:
        out = subprocess.run(["ioreg", "-c", "IOHIDSystem", "-d", "4"],
                             capture_output=True, text=True, timeout=2).stdout
    except Exception:
        return 0.0
    m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
    return int(m.group(1)) / 1e9 if m else 0.0


class Watcher:
    """Fed a reading every few seconds; says when something is worth a word."""

    def __init__(self, away=AWAY_MINUTES * 60, focus=FOCUS_MINUTES * 60):
        self.away = away
        self.focus = focus
        self.was_away_for = 0.0
        self.app = ""
        self.app_since = None
        self.focus_said = False

    def update(self, now, idle_for, app):
        """An instruction for her, or None."""
        if idle_for >= self.away:
            self.was_away_for = max(self.was_away_for, idle_for)
            self.app_since = None   # a break ends a stretch
            return None
        if self.was_away_for:
            gone = self.was_away_for
            self.was_away_for = 0.0
            self.app_since = now
            return self._back(gone)

        if not app or _IGNORED.match(app):
            return None
        if app != self.app:
            self.app, self.app_since, self.focus_said = app, now, False
            return None
        if self.app_since is None:
            self.app_since = now
        if not self.focus_said and now - self.app_since >= self.focus:
            self.focus_said = True
            return self._focus(app, now - self.app_since)
        return None

    @staticmethod
    def _back(seconds):
        minutes = int(seconds // 60)
        span = (f"about {minutes} minutes" if minutes < 90
                else f"about {round(minutes / 60)} hours")
        return ("\n\nThey just came back to the computer after being away for "
                f"{span}. Say one short thing about them being back, in your own "
                "way: not a formal greeting, and don't ask where they went.")

    @staticmethod
    def _focus(app, seconds):
        hours = round(seconds / 3600, 1)
        return (f"\n\nThey have been in {app} without a break for about {hours:g} "
                "hours. Say one short thing about it, the way a friend in the room "
                "would: tease them, ask how it's going, or tell them to stretch. "
                "Don't lecture.")


_watcher = Watcher()


def poll():
    """Take one reading: an instruction for her when there's something to say."""
    if not enabled():
        return None
    return _watcher.update(time.time(), seconds_idle(), frontmost_app())
