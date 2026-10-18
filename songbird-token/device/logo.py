# Idle "logo" screen. Placeholder drawn with primitives so no image is
# needed yet - swap draw_logo() for a drawBitmap of your real logo later
# (convert a <=128x64 1-bit PNG at https://javl.github.io/image2cpp/ ).


def draw_logo(d, status=""):
    d.fill(0)
    # simple bird-ish mark + wordmark, centered
    d.rect(0, 0, 128, 64, 1)
    # body
    d.fill_rect(30, 26, 18, 10, 1)
    # head
    d.fill_rect(44, 22, 8, 8, 1)
    # beak
    d.fill_rect(52, 25, 5, 3, 1)
    # tail
    d.fill_rect(24, 28, 8, 4, 1)
    # wing notch
    d.fill_rect(36, 28, 6, 4, 0)
    d.text("SONGBIRD", 60, 24, 1)
    d.text("token", 60, 34, 1)
    if status:
        d.text(status[:21], 4, 54, 1)
    d.show()
