#!/usr/bin/env python3
# ====================================================================
#  Songbird Pi - OLED readout
#
#  Drives the 0.96" SSD1306 (I2C bus 1, 0x3C) in the same retro dress as
#  the S3 pet: a CRT tube up top showing live vitals, and a readout strip
#  with a twinkling starburst and a leaning seven-segment clock.
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

# The panel's yellow strip is its first 16 rows. Upright, that's the top of
# the picture; turned 180 degrees it's the bottom - so the layout follows it.
STRIP_Y = 0 if ROTATE == 0 else 48
TUBE_Y = 16 if ROTATE == 0 else 0
TUBE_H = 48

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

SEG_W, SEG_H, SEG_T, SEG_SKEW = 7, 13, 2, 3
_SEGS = {"0": 0x3F, "1": 0x06, "2": 0x5B, "3": 0x4F, "4": 0x66, "5": 0x6D,
         "6": 0x7D, "7": 0x07, "8": 0x7F, "9": 0x6F, "-": 0x40}


def _seg_block(c, x, y, w, h, top):
    for j in range(h):
        row = y + j - top
        off = SEG_SKEW * (SEG_H - 1 - row) // (SEG_H - 1)
        c.hline(x + off, y + j, w)


def seg_width(s):
    w = sum(SEG_T + 2 if ch == ":" else SEG_W + 2 for ch in s)
    return w - 2 + SEG_SKEW if w else 0


def seg_text(c, x, y, s, colon=True):
    m = (SEG_H - SEG_T) // 2
    lower = SEG_H - m - SEG_T - 1
    for ch in s:
        if ch == ":":
            if colon:
                _seg_block(c, x, y + 3, SEG_T, SEG_T, y)
                _seg_block(c, x, y + SEG_H - 5, SEG_T, SEG_T, y)
            x += SEG_T + 2
            continue
        on = _SEGS.get(ch, 0)
        parts = [
            (0x01, x + 1, y, SEG_W - 2, SEG_T),
            (0x02, x + SEG_W - SEG_T, y + 1, SEG_T, m - 1),
            (0x04, x + SEG_W - SEG_T, y + m + SEG_T, SEG_T, lower),
            (0x08, x + 1, y + SEG_H - SEG_T, SEG_W - 2, SEG_T),
            (0x10, x, y + m + SEG_T, SEG_T, lower),
            (0x20, x, y + 1, SEG_T, m - 1),
            (0x40, x + 1, y + m, SEG_W - 2, SEG_T),
        ]
        for bit, sx, sy, sw, sh in parts:
            if on & bit:
                _seg_block(c, sx, sy, sw, sh, y)
        x += SEG_W + 2


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


def crt(c):
    """The tube: black past the rounded corners, then the bezel. (No
    scanlines here, unlike the pet: they cut the 5x7 text to pieces.)"""
    r = 7
    for j in range(r):
        for i in range(r):
            if (r - i) ** 2 + (r - j) ** 2 > r * r:
                for x, y in ((i, j), (W - 1 - i, j), (i, TUBE_H - 1 - j), (W - 1 - i, TUBE_H - 1 - j)):
                    c.px(x, TUBE_Y + y, 0)
    c.hline(r, TUBE_Y, W - 2 * r)
    c.hline(r, TUBE_Y + TUBE_H - 1, W - 2 * r)
    c.vline(0, TUBE_Y + r, TUBE_H - 2 * r)
    c.vline(W - 1, TUBE_Y + r, TUBE_H - 2 * r)
    for j in range(r + 1):
        for i in range(r + 1):
            d = (r - i) ** 2 + (r - j) ** 2
            if r * r - r <= d <= r * r + r:
                for x, y in ((i, j), (W - 1 - i, j), (i, TUBE_H - 1 - j), (W - 1 - i, TUBE_H - 1 - j)):
                    c.px(x, TUBE_Y + y)


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
    link = _run(["iw", "dev", "wlan0", "link"])
    v["ssid"], v["signal"] = "", None
    for line in link.splitlines():
        line = line.strip()
        if line.startswith("SSID:"):
            v["ssid"] = line[5:].strip()
        elif line.startswith("signal:"):
            try:
                v["signal"] = int(line.split()[1])
            except (IndexError, ValueError):
                pass
    return v


# --- pages ----------------------------------------------------------------

def page_vitals(c, v, t):
    y = TUBE_Y + 5
    c.text(8, y, "IP " + v.get("ip", "")[:17])
    temp = v.get("temp")
    c.text(8, y + 10, "CPU %s" % (f"{temp:.0f}C" if temp is not None else "--"))
    bar(c, 62, y + 12, 60, (temp or 0) / 85)
    c.text(8, y + 20, "LOAD %.1f" % v.get("load", 0))
    bar(c, 62, y + 22, 60, v.get("load", 0) / 4)
    c.text(8, y + 30, "MEM")
    bar(c, 62, y + 32, 60, v.get("mem", 0))


def page_link(c, v, t):
    y = TUBE_Y + 5
    c.text(8, y, "LINK")
    c.text(38, y, (v.get("ssid") or "not connected")[:14])
    sig = v.get("signal")
    bars = 0 if sig is None else max(0, min(4, (sig + 90) // 10))
    for i in range(4):                                  # signal bars
        h = 3 + i * 3
        x = 10 + i * 6
        if i < bars:
            c.rect(x, y + 26 - h, 4, h)
        else:
            c.hline(x, y + 25, 4)
    c.text(40, y + 14, f"{sig} dBm" if sig is not None else "no signal")
    up = int(v.get("up", 0))
    c.text(8, y + 30, "UP %dd %02dh %02dm" % (up // 86400, up // 3600 % 24, up // 60 % 60))


def page_stars(c, v, t):
    cx, cy = W // 2, TUBE_Y + TUBE_H // 2
    for i in range(36):                                 # flying through space
        a = (i * 2654435761 % 628) / 100
        d = ((t * 22 + i * 37) % 70) + 2
        x = int(cx + math.cos(a) * d * 1.6)
        y = int(cy + math.sin(a) * d * 0.7)
        if not TUBE_Y + 2 <= y < TUBE_Y + TUBE_H - 2:
            continue                                   # stay inside the tube
        if abs(y - cy) < 7 and abs(x - cx) < 38:
            continue                                   # and off the title
        c.px(x, y)
        if d > 40:
            c.px(x + (1 if x > cx else -1), y)
    c.text(cx - 33, cy - 3, "SONGBIRD PI")


PAGES = [page_vitals, page_link, page_stars]
PAGE_S = 6


def draw(c, v, t):
    c.clear()
    page = PAGES[int(t // PAGE_S) % len(PAGES)]
    page(c, v, t)
    crt(c)
    # readout strip: starburst, host name, leaning clock
    twinkle = (t % 3.5) < 0.3
    starburst(c, 3, STRIP_Y + 2, twinkle)
    c.text(20, STRIP_Y + 5, v.get("host", "")[:8])
    hm = time.strftime("%H:%M")
    seg_text(c, W - 2 - seg_width(hm), STRIP_Y + 2, hm, colon=int(t * 2) % 2 == 0)


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
    for n, t in enumerate((1.0, 7.0, 13.4, 14.9)):
        draw(c, fake, t)
        buf = c.rotated()
        img = Image.new("RGB", (W, H))
        for y in range(H):
            for x in range(W):
                if buf[(y >> 3) * W + x] >> (y & 7) & 1:
                    img.putpixel((x, y), (255, 210, 0) if y < 16 else (90, 190, 255))
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
    while True:
        try:
            if panel is None:
                panel = SSD1306(BUS, ADDR)
                print(f"songbird-oled: panel up on i2c-{BUS} 0x{ADDR:02x}", flush=True)
            now = time.time()
            if now - v_at > 2:
                v, v_at = vitals(), now
            if time.monotonic() - init_at > 30:            # keep the panel awake
                panel.init()
                init_at = time.monotonic()
            draw(c, v, time.monotonic())
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
