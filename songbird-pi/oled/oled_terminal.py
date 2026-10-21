#!/usr/bin/env python3
# ====================================================================
#  Songbird Pi - a tiny terminal on the OLED, for when a keyboard is
#  plugged in and no HDMI monitor is.
#
#  A login shell for TERM_USER runs on a pty; the keyboard is read
#  straight from evdev and grabbed (so the hidden HDMI console doesn't
#  also act on the keys); pyte keeps the 21x8 screen; the panel shows it
#  with a blinking block cursor. Unplug the keyboard and it ends.
#
#  Standard library + python3-pyte.
# ====================================================================
import fcntl
import os
import pty
import pwd
import select
import signal
import struct
import termios
import time

import pyte

COLS, ROWS = 21, 8
TERM_USER = os.environ.get("OLED_TERM_USER", "skep")
LAYOUT = os.environ.get("OLED_KBD_LAYOUT", "gb")

EVIOCGRAB = 0x40044590
EV_KEY = 1
_EVENT = struct.Struct("llHHi")          # struct input_event on 64-bit Linux

# --- finding a keyboard -------------------------------------------------

KEY_A, KEY_Z, KEY_SPACE = 30, 44, 57


def _has_key(words, code):
    # /proc lists the KEY bitmap as hex words, most significant first
    bits = 64 if any(len(w) > 8 for w in words) else 32
    idx = len(words) - 1 - code // bits
    return idx >= 0 and int(words[idx], 16) >> (code % bits) & 1


def find_keyboard():
    """/dev/input/eventN of the first device with letter keys and a space
    bar (the HDMI port also calls itself a keyboard, for TV remotes)."""
    try:
        blocks = open("/proc/bus/input/devices").read().split("\n\n")
    except OSError:
        return None
    for b in blocks:
        handlers = key = None
        for line in b.splitlines():
            if line.startswith("H: Handlers="):
                handlers = line.split("=", 1)[1].split()
            elif line.startswith("B: KEY="):
                key = line.split("=", 1)[1].split()
        if not handlers or not key:
            continue
        if all(_has_key(key, k) for k in (KEY_A, KEY_Z, KEY_SPACE)):
            ev = [h for h in handlers if h.startswith("event")]
            if ev:
                return "/dev/input/" + ev[0]
    return None


def hdmi_connected():
    try:
        for name in os.listdir("/sys/class/drm"):
            if "HDMI" in name:
                with open(f"/sys/class/drm/{name}/status") as f:
                    if f.read().strip() == "connected":
                        return True
    except OSError:
        pass
    return False


# --- key codes to characters -------------------------------------------

_ROWS = {
    2: "1!", 3: "2@", 4: "3#", 5: "4$", 6: "5%", 7: "6^", 8: "7&", 9: "8*", 10: "9(", 11: "0)",
    12: "-_", 13: "=+", 26: "[{", 27: "]}", 39: ";:", 40: "'\"", 41: "`~", 43: "\\|",
    51: ",<", 52: ".>", 53: "/?", 57: "  ", 86: "\\|",
}
for _code, _ch in zip(list(range(16, 26)) + list(range(30, 39)) + list(range(44, 51)),
                      "qwertyuiop" "asdfghjkl" "zxcvbnm"):
    _ROWS[_code] = _ch + _ch.upper()
if LAYOUT == "gb":                       # UK: " on shift-2, @ on shift-', # ~ by Enter
    _ROWS.update({3: '2"', 4: "3#", 40: "'@", 43: "#~", 41: "`~", 86: "\\|"})

_SPECIAL = {
    28: "\r", 14: "\x7f", 15: "\t", 1: "\x1b",
    103: "\x1b[A", 108: "\x1b[B", 106: "\x1b[C", 105: "\x1b[D",
    102: "\x1b[H", 107: "\x1b[F", 111: "\x1b[3~", 104: "\x1b[5~", 109: "\x1b[6~",
}
SHIFT, CTRL, ALT, CAPS = {42, 54}, {29, 97}, {56, 100}, 58


class Keys:
    def __init__(self):
        self.down = set()
        self.caps = False

    def feed(self, code, value):
        """value 1 = press, 2 = repeat, 0 = release. Returns bytes to send."""
        if value == 0:
            self.down.discard(code)
            return b""
        self.down.add(code)
        if code == CAPS and value == 1:
            self.caps = not self.caps
            return b""
        if code in _SPECIAL:
            return _SPECIAL[code].encode()
        pair = _ROWS.get(code)
        if not pair:
            return b""
        shift = bool(self.down & SHIFT)
        ch = pair[1] if shift else pair[0]
        if self.caps and ch.isalpha():
            ch = ch.swapcase()
        if self.down & CTRL:
            if ch.isalpha() or ch in "[\\]^_":
                return bytes([ord(ch.upper()) & 0x1F])
            return b""
        out = ch.encode()
        return b"\x1b" + out if self.down & ALT else out


# --- the shell ----------------------------------------------------------

def spawn_shell():
    pw = pwd.getpwnam(TERM_USER)
    pid, fd = pty.fork()
    if pid == 0:
        os.setgid(pw.pw_gid)
        os.initgroups(pw.pw_name, pw.pw_gid)
        os.setuid(pw.pw_uid)
        os.chdir(pw.pw_dir)
        env = {"HOME": pw.pw_dir, "USER": pw.pw_name, "LOGNAME": pw.pw_name,
               "SHELL": pw.pw_shell or "/bin/bash", "TERM": "vt100",
               "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/local/sbin:/usr/sbin:/sbin",
               "LANG": "C.UTF-8", "COLUMNS": str(COLS), "LINES": str(ROWS),
               "SONGBIRD_OLED_TERM": "1"}
        os.execve(pw.pw_shell or "/bin/bash", [pw.pw_shell or "/bin/bash", "-l"], env)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", ROWS, COLS, 0, 0))
    return pid, fd


def render(canvas, screen, blink):
    canvas.clear()
    for y in range(ROWS):
        line = screen.buffer[y]
        text = "".join(line[x].data for x in range(COLS))
        canvas.text(0, y * 8, text)
    cx, cy = screen.cursor.x, screen.cursor.y
    if blink and not screen.cursor.hidden and cx < COLS and cy < ROWS:
        for yy in range(cy * 8, cy * 8 + 8):              # block cursor: invert the cell
            for xx in range(cx * 6, cx * 6 + 6):
                canvas.px(xx, yy, 0 if canvas.get(xx, yy) else 1)


def run(panel, canvas, kbd):
    """Run until the keyboard goes away (or an HDMI monitor turns up)."""
    evfd = os.open(kbd, os.O_RDONLY | os.O_NONBLOCK)
    try:
        fcntl.ioctl(evfd, EVIOCGRAB, 1)                   # keys go only to us
    except OSError:
        pass
    pid, ptyfd = spawn_shell()
    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.ByteStream(screen)
    keys = Keys()
    print(f"songbird-oled: terminal on {kbd}", flush=True)
    last_draw = 0.0
    last_check = time.monotonic()
    try:
        while True:
            r, _, _ = select.select([ptyfd, evfd], [], [], 0.05)
            if ptyfd in r:
                try:
                    data = os.read(ptyfd, 4096)
                except OSError:
                    data = b""
                if not data:                               # shell exited: start a new one
                    os.waitpid(pid, 0)
                    pid, ptyfd = spawn_shell()
                    screen.reset()
                    continue
                stream.feed(data)
            if evfd in r:
                try:
                    raw = os.read(evfd, _EVENT.size * 64)
                except OSError:
                    break                                  # keyboard unplugged
                for i in range(0, len(raw) - _EVENT.size + 1, _EVENT.size):
                    _, _, etype, code, value = _EVENT.unpack_from(raw, i)
                    if etype == EV_KEY:
                        out = keys.feed(code, value)
                        if out:
                            os.write(ptyfd, out)
            now = time.monotonic()
            if now - last_check > 2:
                last_check = now
                if not os.path.exists(kbd) or hdmi_connected():
                    break
            if now - last_draw > 0.08:
                last_draw = now
                render(canvas, screen, int(now * 2) % 2 == 0)
                panel.show(canvas.rotated())
    finally:
        try:
            os.kill(pid, signal.SIGHUP)
            os.waitpid(pid, 0)
        except OSError:
            pass
        for fd in (ptyfd, evfd):
            try:
                os.close(fd)
            except OSError:
                pass
        print("songbird-oled: terminal closed", flush=True)
