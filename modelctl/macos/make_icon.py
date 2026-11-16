#!/usr/bin/env python3
"""Generate modelctl's macOS .icns iconset.

Draws a model list with the active (loaded) model highlighted in the TUI's
cyan. Writes the standard iconset PNGs into the directory given as argv[1];
`install.sh` then runs `iconutil` to compile the .icns. Requires Pillow.
"""
import os
import sys

from PIL import Image, ImageDraw


def rrect(d, box, r, fill):
    d.rounded_rectangle(box, radius=r, fill=fill)


def render(size):
    S = 1024
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = 70
    rrect(d, (m, m, S - m, S - m), 190, (20, 26, 36, 255))   # #141a24 tile
    rrect(d, (m, m, S - m, S // 2), 190, (28, 36, 50, 120))  # top sheen

    rows = 3
    pad_x = 210
    row_h = 118
    gap = 66
    total = rows * row_h + (rows - 1) * gap
    y0 = (S - total) // 2
    cyan = (56, 205, 220, 255)
    gray = (70, 84, 104, 255)
    for i in range(rows):
        y = y0 + i * (row_h + gap)
        active = i == 1
        if active:
            cx = pad_x - 78
            cy = y + row_h // 2
            d.polygon([(cx, cy - 46), (cx + 60, cy), (cx, cy + 46)], fill=cyan)
        rrect(d, (pad_x, y, S - 190, y + row_h), row_h // 2, cyan if active else gray)
        dot_r = 30
        dcx = S - 190 - row_h // 2
        dcy = y + row_h // 2
        d.ellipse(
            (dcx - dot_r, dcy - dot_r, dcx + dot_r, dcy + dot_r),
            fill=(20, 26, 36, 255) if active else (40, 50, 64, 255),
        )
    return img.resize((size, size), Image.LANCZOS)


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    specs = [
        (16, "icon_16x16.png"), (32, "icon_16x16@2x.png"),
        (32, "icon_32x32.png"), (64, "icon_32x32@2x.png"),
        (128, "icon_128x128.png"), (256, "icon_128x128@2x.png"),
        (256, "icon_256x256.png"), (512, "icon_256x256@2x.png"),
        (512, "icon_512x512.png"), (1024, "icon_512x512@2x.png"),
    ]
    for px, name in specs:
        render(px).save(os.path.join(out, name))
    print(f"wrote {len(specs)} pngs to {out}")


if __name__ == "__main__":
    main()
