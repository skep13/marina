"""Clean cel-style hair texture in the original colour: sharper lock shapes,
no strand noise, and a crisp jagged highlight band instead of a soft blur."""
import numpy as np
from PIL import Image, ImageFilter

def sharpen(im, radius, amount):
    a = np.asarray(im).astype(np.float32) / 255
    b = np.asarray(im.filter(ImageFilter.GaussianBlur(radius))).astype(np.float32) / 255
    return np.clip(a + (a - b) * amount, 0, 1)

def process(src, dst, highlight, seed):
    im = Image.open(src).convert("RGBA")
    w, h = im.size
    big = im.resize((w * 2, h * 2), Image.LANCZOS)
    W, H = big.size
    rgb = sharpen(big.convert("RGB"), 14, 0.8)
    alpha = np.asarray(big).astype(np.float32)[..., 3:] / 255
    # posterise gently toward flat lock shapes (cel look), keep the colour
    lum = rgb.mean(-1, keepdims=True)
    smooth = np.asarray(Image.fromarray((rgb * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(7))).astype(np.float32) / 255
    rgb = smooth * 0.7 + rgb * 0.3
    if highlight:
        top, bot = highlight            # band, as fractions from the image top
        rng = np.random.default_rng(seed)
        x = np.arange(W)
        # jagged edges: each lock gets its own length, like painted anime highlights
        locks = np.repeat(rng.uniform(0, 1, W // 40 + 2), 40)[:W]
        edge_t = (top + 0.015 * np.sin(x / 23.0) + 0.02 * locks) * H
        edge_b = (bot - 0.03 * locks - 0.01 * np.cos(x / 31.0)) * H
        # gaps between locks
        gap = (np.abs(((x + 7) % 40) - 20) < 3) | (rng.uniform(0, 1, W) < 0.0)
        y = np.arange(H)[:, None]
        mask = ((y > edge_t[None, :]) & (y < edge_b[None, :]) & ~gap[None, :]).astype(np.float32)
        mask = np.asarray(Image.fromarray((mask * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(1.5))).astype(np.float32)[..., None] / 255
        hl = np.array([0.93, 0.92, 0.97])
        rgb = rgb * (1 - 0.45 * mask) + hl * 0.45 * mask
    out = np.concatenate([np.clip(rgb, 0, 1), alpha], -1)
    Image.fromarray((out * 255 + 0.5).astype(np.uint8)).save(dst)
    print(dst, W, H)

process("hair_17.png", "hair_17_new.png", None, 17)
process("hair_19.png", "hair_19_new.png", None, 19)
