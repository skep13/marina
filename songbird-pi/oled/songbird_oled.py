#!/usr/bin/env python3
# ====================================================================
#  Songbird Pi - OLED readout
#
#  The Pi's front panel on its 0.96" SSD1306 (I2C bus 1, 0x3C), using the
#  whole screen: what the computer is doing - a long command running, with
#  a timer; DONE / FAILED and how long it took when it finishes; messages
#  sent with `oled "..."` - and otherwise a big leaning clock, vitals, the
#  Wi-Fi link and a starfield, in the pet's retro style. Plug in a keyboard
#  (with no HDMI monitor attached) and it becomes a tiny terminal instead
#  (oled_terminal.py).
#
#  Standard library only (no pip, no Pillow), so it runs on first boot
#  before anything has been installed.
#
#    songbird_oled.py                 run on the Pi
#    songbird_oled.py --preview DIR   draw frames to DIR/*.png on a Mac
#                                     (needs Pillow there) to check the look
#  Env: OLED_ROTATE=180 if the panel is mounted upside down,
#       OLED_BUS (default 1), OLED_ADDR (default 0x3c)
# ====================================================================
import math
import os
import socket
import subprocess
import sys
import time

W, H = 128, 64
ROTATE = int(os.environ.get("OLED_ROTATE", "0"))
BUS = int(os.environ.get("OLED_BUS", "1"))
ADDR = int(os.environ.get("OLED_ADDR", "0x3c"), 0)

# 5x7 font, ASCII 32-126: 5 column bytes per glyph, bit 0 = top row
# (the same glyphs as the S3 pet's Adafruit GFX font)
_FONT = bytes.fromhex(
    "000000000000005f00000007000700147f147f14242a7f2a12231308646236495620500008070300001c2241000041221c00"
    "2a1c7f1c2a08083e080800807030000808080808000060600020100804023e5149453e00427f400072494949462141494d33"
    "1814127f1027454545393c4a49493141211109073649494936464949291e0000140000004034000000081422411414141414"
    "004122140802015909063e415d594e7c1211127c7f494949363e414141227f4141413e7f494949417f090909013e41415173"
    "7f0808087f00417f41002040413f017f081422417f404040407f021c027f7f0408107f3e4141413e7f090909063e4151215e"
    "7f09192946264949493203017f01033f4040403f1f2040201f3f4038403f631408146303047804036159494d43007f414141"
    "0204081020004141417f04020102044040404040000307080020545478407f284444383844444428384444287f3854545418"
    "00087e090218a4a49c787f0804047800447d40002040403d007f1028440000417f40007c047804787c080404783844444438"
    "fc1824241818242418fc7c08040408485454542404043f44243c4040207c1c2040201c3c4030403c44281028444c9090907c"
    "4464544c440008364100000077000000413608000201020402"
)


# --- framebuffer --------------------------------------------------------

class Canvas:
    def __init__(self):
        self.buf = bytearray(W * H // 8)       # SSD1306 page layout

    def clear(self):
        self.buf[:] = bytes(len(self.buf))

    def px(self, x, y, on=1):
        if 0 <= x < W and 0 <= y < H:
            i = (y >> 3) * W + x
            if on:
                self.buf[i] |= 1 << (y & 7)
            else:
                self.buf[i] &= ~(1 << (y & 7)) & 0xFF

    def get(self, x, y):
        return self.buf[(y >> 3) * W + x] >> (y & 7) & 1

    def hline(self, x, y, w, on=1):
        for i in range(w):
            self.px(x + i, y, on)

    def vline(self, x, y, h, on=1):
        for j in range(h):
            self.px(x, y + j, on)

    def rect(self, x, y, w, h, on=1):
        for j in range(h):
            self.hline(x, y + j, w, on)

    def line(self, x0, y0, x1, y1, on=1):
        dx, sx = abs(x1 - x0), 1 if x0 < x1 else -1
        dy, sy = -abs(y1 - y0), 1 if y0 < y1 else -1
        err = dx + dy
        while True:
            self.px(x0, y0, on)
            if x0 == x1 and y0 == y1:
                return
            e2 = 2 * err
            if e2 >= dy:
                err += dy
                x0 += sx
            if e2 <= dx:
                err += dx
                y0 += sy

    def text(self, x, y, s):
        for ch in s:
            c = ord(ch)
            if not 32 <= c <= 126:
                c = ord("?")
            g = _FONT[(c - 32) * 5:(c - 32) * 5 + 5]
            for i, col in enumerate(g):
                for j in range(8):
                    if col >> j & 1:
                        self.px(x + i, y + j)
            x += 6
        return x

    def rotated(self):
        if ROTATE != 180:
            return self.buf
        out = Canvas()
        for y in range(H):
            for x in range(W):
                if self.get(x, y):
                    out.px(W - 1 - x, H - 1 - y)
        return out.buf


# --- retro pieces (same shapes as the pet's RetroUI.h) ----------------------

SMALL = (7, 13, 2, 3)        # digit width, height, stroke, lean (the pet's size)
BIG = (21, 40, 5, 6)         # the full-screen clock
MID = (12, 24, 3, 4)         # job timers
_SEGS = {"0": 0x3F, "1": 0x06, "2": 0x5B, "3": 0x4F, "4": 0x66, "5": 0x6D,
         "6": 0x7D, "7": 0x07, "8": 0x7F, "9": 0x6F, "-": 0x40}


def _seg_block(c, x, y, w, h, top, size):
    _, sh, _, skew = size
    for j in range(h):
        row = y + j - top
        off = skew * (sh - 1 - row) // (sh - 1)
        c.hline(x + off, y + j, w)


def seg_width(s, size=SMALL):
    sw, _, st, skew = size
    gap = max(2, st)
    w = sum(st + gap if ch == ":" else sw + gap for ch in s)
    return w - gap + skew if w else 0


def seg_text(c, x, y, s, colon=True, size=SMALL):
    sw, sh, st, _ = size
    gap = max(2, st)
    m = (sh - st) // 2
    lower = sh - m - st - 1
    for ch in s:
        if ch == ":":
            if colon:
                _seg_block(c, x, y + sh // 4, st, st, y, size)
                _seg_block(c, x, y + sh - sh // 4 - st, st, st, y, size)
            x += st + gap
            continue
        on = _SEGS.get(ch, 0)
        parts = [
            (0x01, x + 1, y, sw - 2, st),
            (0x02, x + sw - st, y + 1, st, m - 1),
            (0x04, x + sw - st, y + m + st, st, lower),
            (0x08, x + 1, y + sh - st, sw - 2, st),
            (0x10, x, y + m + st, st, lower),
            (0x20, x, y + 1, st, m - 1),
            (0x40, x + 1, y + m, sw - 2, st),
        ]
        for bit, sx, sy, bw, bh in parts:
            if on & bit:
                _seg_block(c, sx, sy, bw, bh, y, size)
        x += sw + gap


_STAR = ["......X......", "......X......", ".....XXX.....", "..X..XXX..X..",
         "...X.XXX.X...", "....XXXXX....", "XXXXXXXXXXXXX", "....XXXXX....",
         "...X.XXX.X...", "..X..XXX..X..", ".....XXX.....", "......X......",
         "......X......"]
_STAR_SMALL = [".............", ".............", "......X......", "......X......",
               "....X.X.X....", ".....XXX.....", "..XXXXXXXXX..", ".....XXX.....",
               "....X.X.X....", "......X......", "......X......", ".............",
               "............."]


def starburst(c, x, y, twinkle):
    for j, row in enumerate(_STAR_SMALL if twinkle else _STAR):
        for i, ch in enumerate(row):
            if ch == "X":
                c.px(x + i, y + j)


def bar(c, x, y, w, frac):
    """Segmented LED bar, 4 px per segment."""
    frac = max(0.0, min(1.0, frac))
    n = w // 4
    lit = int(n * frac + 0.5)
    for i in range(n):
        if i < lit:
            c.rect(x + i * 4, y, 3, 4)
        else:
            c.px(x + i * 4 + 1, y + 3)


# --- what the Pi knows about itself -------------------------------------

def _read(path, default=""):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return default


def _run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.TimeoutExpired):
        return ""


def vitals():
    v = {"host": socket.gethostname()}
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("1.1.1.1", 80))                 # no packet sent; picks the route
        v["ip"] = s.getsockname()[0]
        s.close()
    except OSError:
        v["ip"] = "no network"
    t = _read("/sys/class/thermal/thermal_zone0/temp")
    v["temp"] = int(t) / 1000 if t.isdigit() else None
    load = _read("/proc/loadavg").split()
    v["load"] = float(load[0]) if load else 0.0
    mem = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, rest = line.partition(":")
        mem[k] = int(rest.split()[0]) if rest.split() else 0
    if mem.get("MemTotal"):
        v["mem"] = 1 - mem.get("MemAvailable", 0) / mem["MemTotal"]
    up = _read("/proc/uptime").split()
    v["up"] = float(up[0]) if up else 0.0
    v["ssid"], v["signal"] = "", None                # signal: 0-100 %
    for line in _run(["nmcli", "-t", "-f", "ACTIVE,SSID,SIGNAL", "dev", "wifi"]).splitlines():
        parts = line.rsplit(":", 1)
        if line.startswith("yes:") and len(parts) == 2:
            v["ssid"] = parts[0][4:].replace("\\:", ":")
            v["signal"] = int(parts[1]) if parts[1].isdigit() else None
            break
    return v


# --- pages: each uses the whole 128x64 panel ----------------------------

def page_clock(c, v, t):
    hm = time.strftime("%H:%M")
    seg_text(c, (W - seg_width(hm, BIG)) // 2, 2, hm, colon=int(t * 2) % 2 == 0, size=BIG)
    date = time.strftime("%a %d %b").upper()
    x = (W - (len(date) * 6 + 17)) // 2
    starburst(c, x, 50, (t % 3.5) < 0.3)
    c.text(x + 17, 54, date)


def page_vitals(c, v, t):
    c.text(0, 0, "IP " + v.get("ip", "")[:18])
    temp = v.get("temp")
    c.text(0, 14, "CPU %s" % (f"{temp:.0f}C" if temp is not None else "--"))
    bar(c, 60, 16, 68, (temp or 0) / 85)
    c.text(0, 27, "LOAD %.1f" % v.get("load", 0))
    bar(c, 60, 29, 68, v.get("load", 0) / 4)
    c.text(0, 40, "MEM %d%%" % round(v.get("mem", 0) * 100))
    bar(c, 60, 42, 68, v.get("mem", 0))
    up = int(v.get("up", 0))
    c.text(0, 55, "UP %dd %02dh %02dm" % (up // 86400, up // 3600 % 24, up // 60 % 60))


def page_link(c, v, t):
    sig = v.get("signal")
    bars = 0 if sig is None else max(1, min(4, (sig + 24) // 25))
    for i in range(4):                                  # big signal bars
        h = 6 + i * 7
        x = 2 + i * 9
        if i < bars:
            c.rect(x, 36 - h, 7, h)
        else:
            c.hline(x, 35, 7)
    c.text(44, 4, "WIFI")
    c.text(44, 16, (v.get("ssid") or "not connected")[:14])
    c.text(44, 28, f"signal {sig}%" if sig is not None else "no signal")
    c.text(0, 44, "IP " + v.get("ip", "")[:18])
    c.text(0, 55, "HOST " + v.get("host", "")[:16])


def page_stars(c, v, t):
    cx, cy = W // 2, H // 2
    for i in range(48):                                 # flying through space
        a = (i * 2654435761 % 628) / 100
        d = ((t * (12 + i % 5 * 7) + i * 37) % 80) + 2   # varied speeds
        x = int(cx + math.cos(a) * d * 1.6)
        y = int(cy + math.sin(a) * d * 0.8)
        if abs(y - cy) < 7 and abs(x - cx) < 38:
            continue                                   # keep off the title
        c.px(x, y)
        if d > 45:
            c.px(x + (1 if x > cx else -1), y)
    c.text(cx - 33, cy - 3, "SONGBIRD PI")


# --- front panel: what the Pi is doing ----------------------------------
# Written by /etc/profile.d/songbird-jobs.sh (long-running commands and their
# results) and by the `oled` command (messages), all under PANEL_DIR.
PANEL_DIR = os.environ.get("OLED_PANEL_DIR", "/run/songbird-oled")
NOTE_S = 20          # how long a done/failed card stays up
RUN_AFTER_S = 5      # a command shows as running once it's taken this long


def _lines(path):
    try:
        with open(path) as f:
            return f.read().split("\n")
    except OSError:
        return None


def panel_state(now=None):
    now = now or time.time()
    st = {"jobs": [], "note": None, "msg": None}
    try:
        names = os.listdir(PANEL_DIR)
    except OSError:
        return st
    for name in names:
        if name.startswith("job."):
            pid = name[4:]
            if not os.path.exists(f"/proc/{pid}"):          # its shell is gone
                try:
                    os.remove(os.path.join(PANEL_DIR, name))
                except OSError:
                    pass
                continue
            ln = _lines(os.path.join(PANEL_DIR, name))
            if ln and len(ln) >= 2 and ln[0].isdigit() and now - int(ln[0]) >= RUN_AFTER_S:
                st["jobs"].append((int(ln[0]), ln[1]))
    ln = _lines(os.path.join(PANEL_DIR, "note"))
    if ln and len(ln) >= 4 and ln[0].isdigit() and now - int(ln[0]) < NOTE_S:
        st["note"] = {"rc": int(ln[1]) if ln[1].lstrip("-").isdigit() else 1,
                      "took": int(ln[2]) if ln[2].isdigit() else 0, "cmd": ln[3]}
    ln = _lines(os.path.join(PANEL_DIR, "msg"))
    if ln and len(ln) >= 3 and ln[0].isdigit() and ln[1].isdigit() and now - int(ln[0]) < int(ln[1]):
        st["msg"] = "\n".join(ln[2:]).strip()
    st["jobs"].sort()
    return st


def _dur(s):
    s = int(s)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"


def _wrap(text, width=21, rows=5):
    out = []
    for para in text.split("\n"):
        words, line = para.split(), ""
        for w in words:
            while len(w) > width:
                if line:
                    out.append(line)
                    line = ""
                out.append(w[:width])
                w = w[width:]
            if len(line) + len(w) + (1 if line else 0) <= width:
                line = f"{line} {w}" if line else w
            else:
                out.append(line)
                line = w
        out.append(line)
    return out[:rows]


def _scroll(c, y, text, t):
    """One line of text; slides sideways if it's wider than the panel."""
    w = len(text) * 6
    if w <= W:
        c.text(0, y, text)
        return
    off = int(t * 30) % (w + 30)
    c.text(-off, y, text)
    c.text(w + 30 - off, y, text)


def page_running(c, jobs, t):
    start, cmd = jobs[int(t // 4) % len(jobs)]           # several: take turns
    c.text(0, 0, "RUNNING" + (f"  {len(jobs)} jobs" if len(jobs) > 1 else ""))
    spin = "|/-\\"[int(t * 6) % 4]
    c.text(W - 6, 0, spin)
    _scroll(c, 12, cmd, t)
    el = _dur(time.time() - start)
    seg_text(c, (W - seg_width(el, MID)) // 2, 26, el, size=MID)
    for i in range(W // 8):                               # marching dots
        if (i + int(t * 8)) % 4 == 0:
            c.rect(i * 8 + 2, 61, 4, 2)


def page_note(c, note, t):
    ok = note["rc"] == 0
    if ok:                                                # tick
        c.line(4, 12, 9, 18)
        c.line(9, 18, 20, 4)
        c.line(4, 13, 9, 19)
        c.line(9, 19, 20, 5)
    else:                                                 # cross
        c.line(4, 4, 18, 18)
        c.line(18, 4, 4, 18)
        c.line(5, 4, 19, 18)
        c.line(19, 4, 5, 18)
    c.text(28, 2, "DONE" if ok else f"FAILED ({note['rc']})")
    c.text(28, 13, "took " + _dur(note["took"]))
    for i, line in enumerate(_wrap(note["cmd"], rows=3)):
        c.text(0, 30 + i * 11, line)


def page_msg(c, msg, t):
    lines = _wrap(msg)
    y = max(0, (H - len(lines) * 12) // 2)
    for i, line in enumerate(lines):
        c.text((W - len(line) * 6) // 2, y + i * 12, line)


PAGES = [page_clock, page_vitals, page_link, page_stars]
PAGE_S = 6


def draw(c, v, t, panel=None):
    """A message beats a fresh done/failed card, which beats a running job;
    otherwise the usual pages take turns."""
    c.clear()
    panel = panel or {}
    if panel.get("msg"):
        page_msg(c, panel["msg"], t)
    elif panel.get("note"):
        page_note(c, panel["note"], t)
    elif panel.get("jobs"):
        page_running(c, panel["jobs"], t)
    else:
        PAGES[int(t // PAGE_S) % len(PAGES)](c, v, t)


# --- the panel ----------------------------------------------------------

class SSD1306:
    INIT = [0xAE, 0xD5, 0x80, 0xA8, 0x3F, 0xD3, 0x00, 0x40, 0x8D, 0x14, 0x20, 0x00,
            0xA1, 0xC8, 0xDA, 0x12, 0x81, 0xCF, 0xD9, 0xF1, 0xDB, 0x40, 0xA4, 0xA6, 0xAF]

    def __init__(self, bus, addr):
        import fcntl
        self.fd = os.open(f"/dev/i2c-{bus}", os.O_RDWR)
        fcntl.ioctl(self.fd, 0x0703, addr)              # I2C_SLAVE
        # These modules have no reset pin, and straight after power-on the
        # first setup sometimes doesn't take: the panel answers but stays
        # dark. Send it twice, a moment apart (and again every 30 s in main).
        self.init()
        time.sleep(0.1)
        self.init()

    def init(self):
        self.cmd(*self.INIT)

    def cmd(self, *c):
        for b in c:
            os.write(self.fd, bytes([0x00, b]))

    def show(self, buf):
        self.cmd(0x21, 0, W - 1, 0x22, 0, H // 8 - 1)
        for i in range(0, len(buf), 128):
            os.write(self.fd, b"\x40" + bytes(buf[i:i + 128]))

    def off(self):
        try:
            self.cmd(0xAE)
        except OSError:
            pass


def preview(out_dir):
    from PIL import Image
    os.makedirs(out_dir, exist_ok=True)
    fake = {"host": "songbird", "ip": "192.168.1.80", "temp": 51.0, "load": 0.62,
            "mem": 0.31, "up": 93784, "ssid": "BT-J2CTPM", "signal": -58}
    c = Canvas()
    for n, t in enumerate((1.0, 7.0, 13.4, 19.9)):
        draw(c, fake, t)
        buf = c.rotated()
        img = Image.new("RGB", (W, H))
        for y in range(H):
            for x in range(W):
                if buf[(y >> 3) * W + x] >> (y & 7) & 1:
                    img.putpixel((x, y), (90, 190, 255))
        img.resize((W * 4, H * 4), Image.NEAREST).save(os.path.join(out_dir, f"frame{n}.png"))
    print("wrote", out_dir)


def main():
    if "--preview" in sys.argv:
        preview(sys.argv[sys.argv.index("--preview") + 1])
        return
    c = Canvas()
    panel = None
    v, v_at = {}, 0.0
    init_at = time.monotonic()
    kbd_check = 0.0
    try:
        import oled_terminal                             # needs python3-pyte
    except ImportError as e:
        oled_terminal = None
        print(f"songbird-oled: no terminal mode ({e})", flush=True)
    while True:
        try:
            if panel is None:
                panel = SSD1306(BUS, ADDR)
                print(f"songbird-oled: panel up on i2c-{BUS} 0x{ADDR:02x}", flush=True)
            # a keyboard and no HDMI monitor: the panel becomes a terminal
            if oled_terminal and time.monotonic() - kbd_check > 2:
                kbd_check = time.monotonic()
                kbd = oled_terminal.find_keyboard()
                if kbd and not oled_terminal.hdmi_connected():
                    oled_terminal.run(panel, c, kbd)
                    panel.init()
                    init_at = time.monotonic()
            now = time.time()
            if now - v_at > 2:
                v, v_at = vitals(), now
            if time.monotonic() - init_at > 30:            # keep the panel awake
                panel.init()
                init_at = time.monotonic()
            draw(c, v, time.monotonic(), panel_state())
            panel.show(c.rotated())
            time.sleep(0.12)
        except OSError as e:
            # no panel yet (not wired, I2C off, wrong address): keep trying
            print(f"songbird-oled: {e}; retrying in 5s", flush=True)
            panel = None
            time.sleep(5)
        except KeyboardInterrupt:
            if panel:
                panel.off()
            return


if __name__ == "__main__":
    main()
