#!/usr/bin/env python3
"""Draw the fastfetch logo for the paper theme: the wallpaper's head as a
braille illustration for a light terminal.

The Miku version (for a dark terminal) puts dots where the picture is light.
Here it's the other way round: dots are ink. Each braille cell is a 2x4 dot
grid; strokes darker than the paper become dots, mid-tones are ordered-
dithered, and each cell takes its colour from the painting itself (warm
greys, the green eyes, the crimson marks). Needs Pillow.

  make-paper-logo.py SOURCE.jpg OUT.ansi [--dark]

--dark: same drawing, light ink for a dark terminal.
"""
import sys
from PIL import Image, ImageFilter, ImageOps

SRC, OUT = sys.argv[1], sys.argv[2]
DARK = "--dark" in sys.argv
COLS, ROWS = 40, 22
BOX = (40, 60, 736, 860)          # head, ear, eyes and the staff's ring
W, H = COLS * 2, ROWS * 4

rgb = Image.open(SRC).convert("RGB").crop(BOX)
grey = ImageOps.autocontrast(rgb.convert("L"), cutoff=1)
small = grey.resize((W, H), Image.LANCZOS)
colour_src = rgb.resize((COLS, ROWS), Image.LANCZOS).filter(ImageFilter.SMOOTH)

BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
BITS = [(0, 0, 0x1), (0, 1, 0x2), (0, 2, 0x4), (1, 0, 0x8), (1, 1, 0x10),
        (1, 2, 0x20), (0, 3, 0x40), (1, 3, 0x80)]
INK = (0x3A, 0x31, 0x2B)
RESET = "\x1b[0m"


def tint(rgb_cell):
    """The cell's own colour, deepened so it reads on paper; greys go to ink."""
    r, g, b = rgb_cell
    sat = max(r, g, b) - min(r, g, b)
    if sat < 40:                                  # hair and lines: warm greys
        k = min(r, g, b) / 255
        if DARK:                                  # light strokes on a dark terminal
            base = tuple(round(0xe9 - (0xe9 - 0x8a) * (1 - k) * 0.8) for _ in range(3))
            base = (base[0], base[1] - 4, base[2] - 8)
        else:
            base = tuple(round(i + (0x9a - i) * k * 0.9) for i in INK)
    elif DARK:                                    # eyes, marks, gold: keep the hue, brighten
        base = tuple(min(255, round(c * 1.25 + 20)) for c in rgb_cell)
    else:                                         # eyes, marks, gold: keep the hue, darken
        base = tuple(round(c * 0.72) for c in rgb_cell)
    return "\x1b[38;2;%d;%d;%dm" % base


lines = []
for cy in range(ROWS):
    line, last = "", None
    for cx in range(COLS):
        bits = 0
        for dx, dy, bit in BITS:
            x, y = cx * 2 + dx, cy * 4 + dy
            v = small.getpixel((x, y))                # 0 black .. 255 paper
            darkness = (255 - v) / 255
            if darkness > 0.08 + BAYER[y % 4][x % 4] / 16 * 0.55:
                bits |= bit
        if bits:
            c = tint(colour_src.getpixel((cx, cy)))
            if c != last:
                line += c
                last = c
            line += chr(0x2800 + bits)
        else:
            line += " "
    lines.append(line.rstrip() + RESET)

with open(OUT, "w") as f:
    f.write("\n".join(lines) + "\n")
print(f"wrote {OUT}: {COLS}x{ROWS}")
