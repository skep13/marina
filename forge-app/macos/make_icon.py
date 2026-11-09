#!/usr/bin/env python3
"""Generate Forge's macOS .icns iconset.

A faceted ember-orange diamond (the ◆ from the app's splash screen) on a dark
warm tile, with a few sparks. Writes the standard iconset PNGs into the
directory given as argv[1]; `install.sh` runs `iconutil` to compile the .icns.
Requires Pillow.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter


def render(size):
    S = 1024
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = 70
    d.rounded_rectangle((m, m, S - m, S - m), radius=190, fill=(28, 24, 19, 255))
    sheen = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).rounded_rectangle((m, m, S - m, S // 2), radius=190, fill=(255, 235, 210, 14))
    img.alpha_composite(sheen)

    # soft glow behind the diamond
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((262, 282, 762, 782), fill=(239, 120, 50, 120))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(80)))
    d = ImageDraw.Draw(img)

    cx, cy, rx, ry = 512, 532, 230, 290
    top, right, bot, left = (cx, cy - ry), (cx + rx, cy), (cx, cy + ry), (cx - rx, cy)
    d.polygon([top, right, (cx, cy)], fill=(247, 160, 92, 255))   # upper-right facet
    d.polygon([top, left, (cx, cy)], fill=(255, 196, 132, 255))   # upper-left (lit)
    d.polygon([bot, left, (cx, cy)], fill=(222, 104, 43, 255))    # lower-left
    d.polygon([bot, right, (cx, cy)], fill=(178, 72, 28, 255))    # lower-right (shade)

    for (x, y, r) in [(760, 300, 18), (812, 382, 11), (270, 760, 13), (726, 790, 9)]:
        d.ellipse((x - r, y - r, x + r, y + r), fill=(255, 190, 120, 230))
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
