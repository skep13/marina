#!/usr/bin/env python3
"""Generate Forge's macOS .icns iconset.

An ember-orange flame (the same paths as the splash screen and the web UI
mark) on a dark warm tile, with a few sparks. Writes the standard iconset PNGs into the
directory given as argv[1]; `install.sh` runs `iconutil` to compile the .icns.
Requires Pillow.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFilter

# 24-unit flame paths, shared with src/splash.html and the dsh-forge-theme mark.
FLAME_OUTER = "M12 1.8 C12.9 5.2 15.6 7.0 17.4 9.6 C18.6 11.3 19.2 13.2 19.2 15.2 C19.2 19.3 16.0 22.4 12.0 22.4 C8.0 22.4 4.8 19.3 4.8 15.4 C4.8 12.9 6.0 10.9 7.7 9.4 C7.8 11.0 8.5 12.3 9.6 13.0 C9.2 8.9 10.4 5.0 12.0 1.8 Z"
FLAME_INNER = "M12.3 10.6 C12.8 13.0 14.4 14.2 15.2 15.8 C15.6 16.5 15.8 17.2 15.8 17.9 C15.8 20.0 14.1 21.5 12.0 21.5 C9.9 21.5 8.2 20.0 8.2 18.0 C8.2 16.6 8.9 15.5 9.9 14.8 C10.0 15.7 10.4 16.4 11.0 16.8 C10.8 14.6 11.3 12.4 12.3 10.6 Z"


def path_points(d, scale, ox, oy, steps=24):
    """Polygon for a path of absolute M/C/Z commands (all these paths use)."""
    t = d.replace("M", " M ").replace("C", " C ").replace("Z", " ").split()
    pts, cur, i = [], None, 0
    while i < len(t):
        if t[i] == "M":
            cur = (float(t[i + 1]), float(t[i + 2])); pts.append(cur); i += 3
        elif t[i] == "C":
            i += 1
            while i < len(t) and t[i] not in ("M", "C"):
                c1, c2, end = [(float(t[i + k]), float(t[i + k + 1])) for k in (0, 2, 4)]
                for n in range(1, steps + 1):
                    u = n / steps; v = 1 - u
                    pts.append(tuple(v**3 * a + 3 * v * v * u * b + 3 * v * u * u * c + u**3 * e
                                     for a, b, c, e in zip(cur, c1, c2, end)))
                cur = end; i += 6
        else:
            i += 1
    return [(ox + x * scale, oy + y * scale) for x, y in pts]


def vgradient(size, box, stops):
    """RGBA layer filled top-to-bottom across box (y0..y1) with colour stops."""
    S = size
    g = Image.new("RGBA", (1, S))
    y0, y1 = box
    for y in range(S):
        f = min(max((y - y0) / (y1 - y0), 0), 1)
        for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
            if p0 <= f <= p1:
                k = (f - p0) / (p1 - p0) if p1 > p0 else 0
                g.putpixel((0, y), tuple(round(a + (b - a) * k) for a, b in zip(c0, c1)) + (255,))
                break
    return g.resize((S, S))


def fill_path(img, pts, layer):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).polygon(pts, fill=255)
    img.paste(layer, (0, 0), mask)


def render(size):
    S = 1024
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    m = 70
    d.rounded_rectangle((m, m, S - m, S - m), radius=190, fill=(28, 24, 19, 255))
    sheen = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(sheen).rounded_rectangle((m, m, S - m, S // 2), radius=190, fill=(255, 235, 210, 14))
    img.alpha_composite(sheen)

    # soft glow behind the flame
    glow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((282, 382, 742, 842), fill=(239, 120, 50, 120))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(80)))

    k, ox, oy = 30, 512 - 12 * 30, 530 - 12.1 * 30   # 24 units -> 720 px, centred
    outer = path_points(FLAME_OUTER, k, ox, oy)
    inner = path_points(FLAME_INNER, k, ox, oy)
    top, bot = oy + 1.8 * k, oy + 22.4 * k
    fill_path(img, outer, vgradient(S, (top, bot), [(0, (255, 178, 87)), (.55, (255, 122, 47)), (1, (194, 65, 12))]))
    fill_path(img, inner, vgradient(S, (oy + 10.6 * k, oy + 21.5 * k), [(0, (255, 208, 138)), (1, (255, 241, 214))]))
    d = ImageDraw.Draw(img)

    for (x, y, r) in [(760, 250, 18), (812, 340, 11), (240, 330, 13), (300, 250, 9)]:
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
