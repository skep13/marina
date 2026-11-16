"""The commands aiws.screen runs on Hyprland and X11, without a display."""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from aiws import screen  # noqa: E402


class Calls:
    def __init__(self, stdout=""):
        self.cmds, self.stdout = [], stdout

    def __call__(self, cmd, **kw):
        self.cmds.append(cmd)
        return mock.Mock(returncode=0, stdout=self.stdout, stderr="")


HYPR = {"HYPRLAND_INSTANCE_SIGNATURE": "x", "WAYLAND_DISPLAY": "wayland-1"}


class Hyprland(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, HYPR, clear=True)
        self.env.start()
        self.which = mock.patch("shutil.which", return_value="/usr/bin/hyprctl")
        self.which.start()
        mock.patch("sys.platform", "linux").start()   # tests run on the Mac too

    def tearDown(self):
        mock.patch.stopall()

    def test_backend(self):
        self.assertEqual(screen.backend(), "hyprland")

    def test_key_combo_presses_and_releases_modifiers(self):
        c = Calls()
        with mock.patch("subprocess.run", c):
            screen.key("ctrl+shift+t")
        self.assertEqual(c.cmds[0], ["wtype", "-M", "ctrl", "-M", "shift", "-k", "t",
                                     "-m", "shift", "-m", "ctrl"])

    def test_single_key(self):
        c = Calls()
        with mock.patch("subprocess.run", c):
            screen.key("Return")
        self.assertEqual(c.cmds[0], ["wtype", "-k", "Return"])

    def test_super_maps_to_logo(self):
        c = Calls()
        with mock.patch("subprocess.run", c):
            screen.key("super+1")
        self.assertEqual(c.cmds[0][:3], ["wtype", "-M", "logo"])

    def test_click_moves_then_clicks(self):
        c = Calls()
        with mock.patch("subprocess.run", c):
            screen.click(120.7, 300, button=3)
        self.assertEqual(c.cmds[0], ["hyprctl", "dispatch", "hl.dsp.cursor.move({ x = 120, y = 300 })"])
        self.assertEqual(c.cmds[1], ["ydotool", "click", "0xC1"])

    def test_click_falls_back_to_classic_dispatch(self):
        calls = []
        def run(cmd, **kw):
            calls.append(cmd)
            lua = len(cmd) == 3 and cmd[2].startswith("hl.dsp")
            return mock.Mock(returncode=0, stdout="error: unknown" if lua else "ok", stderr="")
        with mock.patch("subprocess.run", run):
            screen.click(5, 6)
        self.assertEqual(calls[1], ["hyprctl", "dispatch", "movecursor", "5", "6"])

    def test_active_window_from_hyprctl(self):
        c = Calls('{"class":"codium","title":"x.py","at":[10,40],"size":[800,600]}')
        with mock.patch("subprocess.run", c):
            w = screen.active_window()
        self.assertEqual(w, {"app": "codium", "title": "x.py", "x": 10, "y": 40, "w": 800, "h": 600})

    def test_window_capture_uses_geometry(self):
        c = Calls('{"class":"a","title":"b","at":[5,6],"size":[70,80]}')
        with mock.patch("subprocess.run", c), mock.patch("pathlib.Path.read_bytes", return_value=b"png"):
            self.assertEqual(screen.capture(window_only=True), b"png")
        grim = [x for x in c.cmds if x[0] == "grim"][0]
        self.assertEqual(grim[1:3], ["-g", "5,6 70x80"])

    def test_selection_uses_wl_paste(self):
        c = Calls("picked text")
        with mock.patch("subprocess.run", c):
            self.assertEqual(screen.selection(), "picked text")
        self.assertEqual(c.cmds[0][0], "wl-paste")


class X11(unittest.TestCase):
    def test_backend_and_click(self):
        with mock.patch.dict(os.environ, {"DISPLAY": ":0"}, clear=True), mock.patch("sys.platform", "linux"):
            self.assertEqual(screen.backend(), "x11")
            c = Calls()
            with mock.patch("subprocess.run", c):
                screen.click(1, 2)
            self.assertEqual(c.cmds[0][:2], ["xdotool", "mousemove"])


class MacOS(unittest.TestCase):
    def setUp(self):
        mock.patch("sys.platform", "darwin").start()

    def tearDown(self):
        mock.patch.stopall()

    def test_backend(self):
        self.assertEqual(screen.backend(), "macos")

    def test_key_scripts(self):
        self.assertEqual(screen._mac_key_script("cmd+shift+t"),
                         'tell application "System Events" to keystroke "t" using {command down, shift down}')
        self.assertEqual(screen._mac_key_script("Return"), 'tell application "System Events" to key code 36')

    def test_window_without_accessibility_gives_app_only(self):
        c = Calls("Finder")
        with mock.patch("subprocess.run", c):
            self.assertEqual(screen.active_window(), {"app": "Finder", "title": ""})


if __name__ == "__main__":
    unittest.main()
