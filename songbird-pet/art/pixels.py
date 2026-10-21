import sys, math
from PIL import Image, ImageDraw
W, H = 44, 48
def blank(): return [[0]*W for _ in range(H)]
def px(g, x, y, v=1):
    if 0 <= x < W and 0 <= y < H: g[y][x] = v
def ellipse(g, cx, cy, rx, ry, v=1, fill=False):
    for y in range(H):
        for x in range(W):
            d = ((x-cx)/rx)**2 + ((y-cy)/ry)**2
            if (d <= 1.0) if fill else (0.62 <= d <= 1.0): px(g, x, y, v)
def poly(g, pts, v=1):
    im = Image.new('1', (W, H)); ImageDraw.Draw(im).polygon(pts, fill=1)
    for y in range(H):
        for x in range(W):
            if im.getpixel((x, y)): px(g, x, y, v)
def line(g, x0, y0, x1, y1, v=1):
    im = Image.new('1', (W, H)); ImageDraw.Draw(im).line((x0, y0, x1, y1), fill=1)
    for y in range(H):
        for x in range(W):
            if im.getpixel((x, y)): px(g, x, y, v)

def marina(eyes="open"):
    g = blank()
    cx = 22
    # halo
    ellipse(g, cx, 2, 8, 2.2)
    # hair mass (light): dome + long wavy sides
    ellipse(g, cx, 16, 13, 12, fill=True)
    poly(g, [(9,14),(35,14),(38,26),(39,33),(36,38),(33,36),(31,40),(28,34),(16,34),(13,40),(11,36),(8,38),(5,33),(6,26)])
    # face (dark), framed by hair, bangs cut jagged across the forehead
    poly(g, [(14,17),(30,17),(30,27),(27,31),(24,33),(20,33),(17,31),(14,27)], 0)
    for x, depth in [(14,3),(16,5),(18,2),(20,4),(22,6),(24,3),(26,5),(28,2),(29,4)]:
        line(g, x, 16, x+1, 16+depth, 1)            # bang strands hanging over the forehead
    # ribbon on her right (viewer's left): dark bow cut into the hair
    poly(g, [(8,9),(12,11),(8,13)], 0); poly(g, [(16,9),(12,11),(16,13)], 0)
    line(g, 12, 11, 11, 15, 0); line(g, 12, 11, 13, 15, 0)
    px(g, 12, 11, 1)
    # eyes
    for ex in (16, 24):
        if eyes == "open":
            poly(g, [(ex,22),(ex+4,22),(ex+4,27),(ex,27)], 1)      # iris block
            poly(g, [(ex+1,23),(ex+3,23),(ex+3,26),(ex+1,26)], 0)  # pupil
            px(g, ex+1, 23, 1)                                      # highlight
            line(g, ex-1, 21, ex+5, 21, 1)                          # upper lash
        elif eyes == "closed":
            line(g, ex-1, 25, ex+5, 25, 1)
            px(g, ex-1, 24); px(g, ex+5, 24)
        elif eyes == "happy":
            line(g, ex, 25, ex+2, 23, 1); line(g, ex+2, 23, ex+4, 25, 1)
    # mouth
    line(g, 21, 30, 23, 30, 1)
    # neck + choker with a little pendant
    line(g, 19, 34, 19, 35, 1); line(g, 25, 34, 25, 35, 1)
    line(g, 18, 36, 26, 36, 1); px(g, 22, 37, 1)
    # hoodie: shoulders, hood edges, drawstrings, moon print
    line(g, 16, 37, 4, 43, 1); line(g, 4, 43, 1, 47, 1)
    line(g, 28, 37, 40, 43, 1); line(g, 40, 43, 43, 47, 1)
    line(g, 16, 37, 20, 42, 1); line(g, 28, 37, 24, 42, 1)       # hood opening
    line(g, 19, 42, 19, 47, 1); line(g, 25, 42, 25, 47, 1)       # drawstrings
    px(g, 19, 47, 0); px(g, 25, 47, 0)
    for (x, y) in [(22,44),(21,45),(21,46),(22,47)]: px(g, x, y)  # crescent moon
    px(g, 23, 43); px(g, 9, 45); px(g, 34, 45)                    # sparkles / hoodie seams
    return g

def show(gs, path, S=8):
    sheet = Image.new('RGB', (len(gs)*(W*S+16), H*S), (30,30,30))
    for i, g in enumerate(gs):
        for y in range(H):
            for x in range(W):
                if g[y][x]:
                    for yy in range(S-1):
                        for xx in range(S-1): sheet.putpixel((i*(W*S+16)+x*S+xx, y*S+yy), (90,190,255))
    sheet.save(path)
if __name__ == "__main__":
    show([marina("open"), marina("closed"), marina("happy")], sys.argv[1])
