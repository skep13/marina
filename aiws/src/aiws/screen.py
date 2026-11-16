"""The screen, the pointer and the keyboard, on Hyprland (Wayland), X11 or
macOS (for building and testing on the Mac).

Hyprland: window info from `hyprctl`, screenshots with `grim`, typing with
`wtype` (the virtual-keyboard protocol, no extra rights), pointer moves
with `hyprctl dispatch movecursor` and clicks with `ydotool` (needs
ydotoold and /dev/uinput). X11: xdotool, xprop, maim, xclip.

macOS: AppleScript (System Events) for windows and keys, `screencapture`,
CoreGraphics through ctypes for clicks. Needs Screen Recording and
Accessibility permission for whatever runs this.

Coordinates are global logical pixels everywhere.

  python -m aiws.screen window | selection | capture [file.png] | serve
"""
import json
import os
import shutil
import sys
import subprocess
import tempfile
from pathlib import Path


def backend():
    if sys.platform == "darwin":
        return "macos"
    if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
        return "hyprland"
    if os.environ.get("DISPLAY"):
        return "x11"
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"  # some other compositor: screenshots only, via grim
    return "none"


def _run(cmd, input=None, timeout=5):
    return subprocess.run(cmd, capture_output=True, text=input is None or isinstance(input, str),
                          input=input, timeout=timeout)


def _out(cmd):
    try:
        return _run(cmd).stdout.strip()
    except Exception:
        return ""


def active_window():
    """{'app', 'title', 'x', 'y', 'w', 'h'} of the focused window, or {}."""
    b = backend()
    if b == "hyprland":
        try:
            w = json.loads(_out(["hyprctl", "activewindow", "-j"]) or "{}")
        except ValueError:
            return {}
        if not w:
            return {}
        (x, y), (wd, ht) = w.get("at", [0, 0]), w.get("size", [0, 0])
        return {"app": w.get("class", ""), "title": w.get("title", ""),
                "x": x, "y": y, "w": wd, "h": ht}
    if b == "macos":
        out = _out(["osascript", "-e", _MAC_WINDOW])
        parts = out.split("\t")
        if not parts or not parts[0]:
            return {}
        w = {"app": parts[0], "title": parts[1] if len(parts) > 1 else ""}
        try:
            w.update(x=int(parts[2]), y=int(parts[3]), w=int(parts[4]), h=int(parts[5]))
        except (IndexError, ValueError):
            pass                      # no Accessibility permission: app name only
        return w
    if b == "x11":
        wid = _out(["xdotool", "getactivewindow"])
        if not wid:
            return {}
        geo = dict(line.split("=", 1) for line in
                   _out(["xdotool", "getwindowgeometry", "--shell", wid]).splitlines() if "=" in line)
        cls = _out(["xprop", "-id", wid, "WM_CLASS"]).split("=")[-1].replace('"', "").strip()
        return {"app": cls.split(",")[-1].strip(), "title": _out(["xdotool", "getwindowname", wid]),
                "x": int(geo.get("X", 0)), "y": int(geo.get("Y", 0)),
                "w": int(geo.get("WIDTH", 0)), "h": int(geo.get("HEIGHT", 0))}
    return {}


def selection(limit=4000):
    """The primary selection: whatever text is highlighted right now."""
    b = backend()
    if b in ("hyprland", "wayland"):
        return _out(["wl-paste", "--primary", "--no-newline"])[:limit]
    if b == "x11":
        return _out(["xclip", "-o", "-selection", "primary"])[:limit]
    return ""                         # macOS has no primary selection


def capture(window_only=False):
    """PNG bytes of the screen, or of the focused window."""
    f = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    try:
        b = backend()
        if b in ("hyprland", "wayland"):
            args = ["grim"]
            w = active_window() if window_only else {}
            if w:
                args += ["-g", f"{w['x']},{w['y']} {w['w']}x{w['h']}"]
            subprocess.run(args + [f], check=True, timeout=10)
        elif b == "macos":
            args = ["screencapture", "-x", "-t", "png"]
            w = active_window() if window_only else {}
            if w.get("w"):
                args += ["-R", f"{w['x']},{w['y']},{w['w']},{w['h']}"]
            subprocess.run(args + [f], check=True, timeout=10)
        elif b == "x11":
            args = ["maim"]
            if window_only:
                args += ["-i", _out(["xdotool", "getactivewindow"])]
            subprocess.run(args + [f], check=True, timeout=10)
        else:
            raise RuntimeError("no display to capture")
        return Path(f).read_bytes()
    finally:
        os.unlink(f)


def hypr_dispatch(lua, legacy):
    """Run a Hyprland dispatcher. Hyprland with a Lua config (0.55+) takes
    Lua (`hl.dsp...`); older ones take the classic words. Try Lua first."""
    r = _run(["hyprctl", "dispatch", lua])
    if r.returncode == 0 and "error" not in (r.stdout + r.stderr).lower():
        return
    subprocess.run(["hyprctl", "dispatch", *legacy], check=True, capture_output=True, timeout=5)


def click(x, y, button=1):
    b = backend()
    if b == "hyprland":
        hypr_dispatch(f"hl.dsp.cursor.move({{ x = {int(x)}, y = {int(y)} }})",
                      ["movecursor", str(int(x)), str(int(y))])
        # ydotool button codes: 0xC0 left, 0xC1 right, 0xC2 middle (down+up)
        code = {1: "0xC0", 2: "0xC2", 3: "0xC1"}.get(int(button), "0xC0")
        r = _run(["ydotool", "click", code])
        if r.returncode != 0:
            raise RuntimeError("ydotool couldn't click; is ydotool.service running? "
                               + (r.stderr or "").strip()[-200:])
    elif b == "x11":
        subprocess.run(["xdotool", "mousemove", str(int(x)), str(int(y)), "click", str(button)],
                       check=True, timeout=5)
    elif b == "macos":
        _mac_click(x, y, button)
    else:
        raise RuntimeError("clicking isn't supported on this display")


def type_text(text):
    b = backend()
    if b in ("hyprland", "wayland"):
        subprocess.run(["wtype", "-d", "8", "--", text], check=True, timeout=60)
    elif b == "x11":
        subprocess.run(["xdotool", "type", "--delay", "8", "--", text], check=True, timeout=60)
    elif b == "macos":
        lit = text.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(["osascript", "-e", f'tell application "System Events" to keystroke "{lit}"'],
                       check=True, timeout=60)
    else:
        raise RuntimeError("typing isn't supported on this display")


_MODS = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift", "alt": "alt",
         "super": "logo", "meta": "logo", "win": "logo", "cmd": "logo"}


def key(combo):
    """A combination like 'ctrl+s', 'ctrl+shift+t', 'Return', 'super+1'."""
    b = backend()
    if b in ("hyprland", "wayland"):
        parts = [p for p in combo.replace(" ", "").split("+") if p]
        mods = [_MODS[p.lower()] for p in parts[:-1] if p.lower() in _MODS]
        args = ["wtype"]
        for m in mods:
            args += ["-M", m]
        args += ["-k", parts[-1]]
        for m in reversed(mods):
            args += ["-m", m]
        subprocess.run(args, check=True, timeout=5)
    elif b == "x11":
        subprocess.run(["xdotool", "key", "--", combo], check=True, timeout=5)
    elif b == "macos":
        subprocess.run(["osascript", "-e", _mac_key_script(combo)], check=True, timeout=5)
    else:
        raise RuntimeError("key presses aren't supported on this display")


# ---- macOS -------------------------------------------------------------------

_MAC_WINDOW = '''
tell application "System Events"
  set p to first application process whose frontmost is true
  set out to name of p
  try
    set w to front window of p
    set {x, y} to position of w
    set {ww, hh} to size of w
    set out to out & tab & (name of w) & tab & x & tab & y & tab & ww & tab & hh
  end try
  return out
end tell'''

_MAC_KEYCODES = {"return": 36, "enter": 36, "tab": 48, "space": 49, "backspace": 51,
                 "delete": 51, "escape": 53, "esc": 53, "left": 123, "right": 124,
                 "down": 125, "up": 126, "home": 115, "end": 119, "pageup": 116, "pagedown": 121}
_MAC_MODS = {"ctrl": "control down", "control": "control down", "shift": "shift down",
             "alt": "option down", "option": "option down", "cmd": "command down",
             "command": "command down", "super": "command down", "meta": "command down"}


def _mac_key_script(combo):
    parts = [p for p in combo.replace(" ", "").split("+") if p]
    mods = [_MAC_MODS[p.lower()] for p in parts[:-1] if p.lower() in _MAC_MODS]
    k = parts[-1]
    using = f" using {{{', '.join(mods)}}}" if mods else ""
    if k.lower() in _MAC_KEYCODES:
        press = f"key code {_MAC_KEYCODES[k.lower()]}"
    else:
        press = 'keystroke "' + k.lower().replace('"', '\\"') + '"'
    return f'tell application "System Events" to {press}{using}'


def _mac_click(x, y, button=1):
    import ctypes
    import ctypes.util
    cg = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreGraphics"))

    class CGPoint(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double)]

    cg.CGEventCreateMouseEvent.restype = ctypes.c_void_p
    cg.CGEventCreateMouseEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint32, CGPoint, ctypes.c_uint32]
    cg.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
    cg.CFRelease = ctypes.cdll.LoadLibrary(ctypes.util.find_library("CoreFoundation")).CFRelease
    cg.CFRelease.argtypes = [ctypes.c_void_p]
    down, up, btn = {1: (1, 2, 0), 3: (3, 4, 1)}.get(int(button), (1, 2, 0))  # left / right
    pt = CGPoint(float(x), float(y))
    for kind in (5, down, up):                     # move, press, release
        ev = cg.CGEventCreateMouseEvent(None, kind, pt, btn)
        cg.CGEventPost(0, ev)                      # kCGHIDEventTap
        cg.CFRelease(ev)


def serve():
    """One request per line on stdin, one JSON reply per line on stdout:
    window | selection | capture [--window] (replies with base64 PNG).
    Lets the sphere app ask cheaply without starting Python each time."""
    import base64
    for line in sys.stdin:
        cmd = line.strip()
        try:
            if cmd == "window":
                reply = {"ok": True, "backend": backend(), **active_window()}
            elif cmd == "selection":
                reply = {"ok": True, "text": selection()}
            elif cmd.startswith("capture"):
                png = capture(window_only="--window" in cmd)
                reply = {"ok": True, "png": base64.b64encode(png).decode()}
            else:
                reply = {"ok": False, "error": f"unknown command {cmd!r}"}
        except Exception as e:
            reply = {"ok": False, "error": str(e)[-300:]}
        sys.stdout.write(json.dumps(reply) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "window"
    if cmd == "serve":
        serve()
        sys.exit()
    if cmd == "window":
        print(json.dumps({"backend": backend(), **active_window()}))
    elif cmd == "selection":
        print(selection())
    elif cmd == "capture":
        data = capture(window_only="--window" in sys.argv)
        out = next((a for a in sys.argv[2:] if not a.startswith("--")), None)
        if out:
            Path(out).write_bytes(data)
            print(out)
        else:
            sys.stdout.buffer.write(data)
    else:
        sys.exit(__doc__)
