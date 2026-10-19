#pragma once
// ============================================================
// Scenes - full-screen pictures that replace the eyes while the Mac says
// what they're up to (the record player lives in RoboEyesManager).
// ============================================================
// Each draws into the blue area (EYES_ZONE_*) from millis() alone, so it
// animates at whatever rate the eyes engine redraws. Clean screens: no CRT
// bezel or scanlines.
#include <math.h>
#include <Adafruit_SSD1306.h>
#include "Config.h"

namespace Scenes {

static const int TOP = EYES_ZONE_Y, H = EYES_ZONE_HEIGHT, W = SCREEN_WIDTH;

inline uint32_t hash(uint32_t x) {
    x ^= x >> 16; x *= 0x7feb352dU; x ^= x >> 15; x *= 0x846ca68bU; x ^= x >> 16;
    return x;
}

// Draws "words" (2-3px bars) for line `line`, up to `upto` px of its length.
// Returns where the line ends (or stops).
inline int wordBars(Adafruit_SSD1306 &d, int x0, int y, int maxW, uint32_t line, int upto, int h = 3) {
    int x = x0, end = x0 + maxW, k = 0;
    while (x < end && x - x0 < upto) {
        int w = 6 + (hash(line * 31 + k) % 5) * 4;
        if (x + w > end) w = end - x;
        int shown = w;
        if (x - x0 + w > upto) shown = upto - (x - x0);
        if (shown > 0) d.fillRect(x, y, shown, h, SSD1306_WHITE);
        x += w + 4;
        k++;
        if (k > 1 && hash(line * 7 + k) % 4 == 0) break;      // lines end raggedly
    }
    return x0 + (upto < x - x0 ? upto : x - x0);
}

// --- coding: a terminal typing ---------------------------------------------
inline void code(Adafruit_SSD1306 &d, unsigned long ms) {
    const int lineH = 7, rows = 6, lineMs = 1800;
    unsigned long cur = ms / lineMs;
    int typed = (int)((ms % lineMs) * 130 / (lineMs - 400));     // px of current line
    for (int r = 0; r < rows; r++) {
        uint32_t line = cur - (rows - 1 - r);
        int y = TOP + 3 + r * lineH;
        int indent = (hash(line) % 4) * 8;
        if (r == rows - 1) {
            // prompt + the line being typed + a blinking block cursor
            d.drawLine(2, y, 5, y + 2, SSD1306_WHITE);
            d.drawLine(5, y + 2, 2, y + 4, SSD1306_WHITE);
            int endX = wordBars(d, 10 + indent, y + 1, 110 - indent, line, typed);
            if ((ms / 350) % 2) d.fillRect(endX + 2, y - 1, 4, 7, SSD1306_WHITE);
        } else {
            wordBars(d, 10 + indent, y + 1, 110 - indent, line, 999);
        }
    }
}

// --- gaming: a little space shooter -----------------------------------------
inline void game(Adafruit_SSD1306 &d, unsigned long ms) {
    static const uint8_t INV[2][6] = {                              // 8x6, two frames
        {0x24, 0x7E, 0xDB, 0xFF, 0xA5, 0x24},
        {0x24, 0x7E, 0xDB, 0xFF, 0x5A, 0x81},
    };
    static const uint8_t SHIP[5][2] = {                             // 9x5
        {0x08, 0x00}, {0x1C, 0x00}, {0x3E, 0x00}, {0xFF, 0x80}, {0xE3, 0x80},
    };
    for (int i = 0; i < 14; i++) {                                   // starfield drifting down
        int x = hash(i) % W;
        int y = (hash(i + 99) % H + ms / (40 + (i % 3) * 30)) % H;
        d.drawPixel(x, TOP + y, SSD1306_WHITE);
    }
    int frame = (ms / 400) % 2;
    int step = (ms / 400) % 24;
    int march = step < 12 ? step * 2 : (24 - step) * 2;               // left-right
    for (int row = 0; row < 2; row++) {
        for (int col = 0; col < 6; col++) {
            int x = 18 + col * 15 + march, y = TOP + 3 + row * 10;
            for (int j = 0; j < 6; j++)
                for (int i = 0; i < 8; i++)
                    if (INV[frame][j] & (0x80 >> i)) d.drawPixel(x + i, y + j, SSD1306_WHITE);
        }
    }
    float shipX = W / 2 + 44 * sinf(ms / 900.0f);
    int sx = (int)shipX - 4, sy = TOP + H - 7;
    for (int j = 0; j < 5; j++)
        for (int i = 0; i < 9; i++)
            if (SHIP[j][i / 8] & (0x80 >> (i % 8))) d.drawPixel(sx + i, sy + j, SSD1306_WHITE);
    for (int k = 0; k < 3; k++) {                                     // shots
        unsigned long age = (ms + k * 300) % 900;
        unsigned long fired = ms - age;
        int x = (int)(W / 2 + 44 * sinf(fired / 900.0f));
        int y = sy - 2 - (int)(age * (H - 10) / 900);
        if (y > TOP) d.drawFastVLine(x, y, 3, SSD1306_WHITE);
    }
}

// --- call: an oscilloscope trace of a voice ----------------------------------
inline void call(Adafruit_SSD1306 &d, unsigned long ms) {
    const int mid = TOP + H / 2;
    for (int x = 0; x < W; x += 4) d.drawPixel(x, mid, SSD1306_WHITE);       // graticule
    for (int y = TOP + 4; y < TOP + H; y += 4) {
        d.drawPixel(W / 4, y, SSD1306_WHITE);
        d.drawPixel(W / 2, y, SSD1306_WHITE);
        d.drawPixel(3 * W / 4, y, SSD1306_WHITE);
    }
    float talk = 0.35f + 0.65f * fabsf(sinf(ms / 610.0f)) * (0.55f + 0.45f * sinf(ms / 170.0f));
    int py = mid;
    for (int x = 0; x < W; x++) {
        float env = 0.4f + 0.6f * fabsf(sinf(ms / 700.0f + x * 0.03f));
        float v = sinf(x * 0.29f - ms / 80.0f) + 0.4f * sinf(x * 0.71f + ms / 53.0f);
        int y = mid + (int)(talk * env * 13 * v);
        if (x) d.drawLine(x - 1, py, x, y, SSD1306_WHITE);
        py = y;
    }
}

// --- browsing: a radar sweep -------------------------------------------------
inline void radar(Adafruit_SSD1306 &d, unsigned long ms) {
    const int cx = W / 2, cy = TOP + H / 2, r = H / 2 - 2;
    d.drawCircle(cx, cy, r, SSD1306_WHITE);
    for (int a = 0; a < 360; a += 12) {                                      // inner ring, dotted
        float t = a * (float)M_PI / 180;
        d.drawPixel(cx + (int)(r * 0.55f * cosf(t)), cy + (int)(r * 0.55f * sinf(t)), SSD1306_WHITE);
    }
    for (int i = -r; i <= r; i += 3) {                                       // crosshair
        d.drawPixel(cx + i, cy, SSD1306_WHITE);
        d.drawPixel(cx, cy + i, SSD1306_WHITE);
    }
    float sweep = fmodf(ms * 0.0028f, 2 * (float)M_PI);
    d.drawLine(cx, cy, cx + (int)(r * cosf(sweep)), cy + (int)(r * sinf(sweep)), SSD1306_WHITE);
    for (int k = 1; k <= 4; k++) {                                           // fading trail
        float a = sweep - k * 0.09f;
        for (int s = 3; s < r; s += 1 + k)
            d.drawPixel(cx + (int)(s * cosf(a)), cy + (int)(s * sinf(a)), SSD1306_WHITE);
    }
    for (int b = 0; b < 5; b++) {                                            // blips
        float ba = (hash(b + (ms / 9000) * 5) % 628) / 100.0f;
        float br = r * (0.25f + (hash(b * 13 + 1) % 70) / 100.0f);
        float since = fmodf(sweep - ba + 4 * (float)M_PI, 2 * (float)M_PI);
        if (since < 2.4f) {
            int bx = cx + (int)(br * cosf(ba)), by = cy + (int)(br * sinf(ba));
            if (since < 0.9f) d.fillRect(bx - 1, by - 1, 3, 3, SSD1306_WHITE);
            else d.drawPixel(bx, by, SSD1306_WHITE);
        }
    }
    // range ticks either side, for the instrument look
    for (int i = 0; i < 5; i++) {
        d.drawFastHLine(6, TOP + 6 + i * 9, i % 2 ? 4 : 8, SSD1306_WHITE);
        d.drawFastHLine(W - 6 - (i % 2 ? 4 : 8), TOP + 6 + i * 9, i % 2 ? 4 : 8, SSD1306_WHITE);
    }
}

// --- chatting: two bubbles taking turns -------------------------------------
inline void bubble(Adafruit_SSD1306 &d, int x, int y, int w, bool tailLeft, int phase, uint32_t seed,
                   unsigned long ms) {
    d.drawRoundRect(x, y, w, 17, 6, SSD1306_WHITE);
    int tx = tailLeft ? x + 8 : x + w - 12;
    d.fillTriangle(tx, y + 16, tx + 6, y + 16, tailLeft ? tx - 2 : tx + 8, y + 21, SSD1306_WHITE);
    d.drawFastHLine(tx + 1, y + 16, 5, SSD1306_BLACK);
    if (phase == 0) {                                                        // typing dots
        for (int i = 0; i < 3; i++) {
            int bounce = ((ms / 150 + 3 - i) % 3 == 0) ? -2 : 0;
            d.fillRect(x + w / 2 - 9 + i * 7, y + 7 + bounce, 3, 3, SSD1306_WHITE);
        }
    } else {
        wordBars(d, x + 6, y + 4, w - 12, seed, 999, 2);
        wordBars(d, x + 6, y + 10, w - 24, seed + 1, 999, 2);
    }
}

inline void chat(Adafruit_SSD1306 &d, unsigned long ms) {
    const unsigned long cycle = 5200;
    unsigned long t = ms % cycle;
    uint32_t round = ms / cycle;
    bubble(d, 4, TOP + 1, 78, true, t < 1300 ? 0 : 1, round * 2, ms);
    if (t >= 2200)
        bubble(d, W - 4 - 78, TOP + 24, 78, false, t < 3600 ? 0 : 1, round * 2 + 1, ms);
}

// --- making: a 3D printer building a vase -----------------------------------
inline void printer(Adafruit_SSD1306 &d, unsigned long ms) {
    const int left = 30, right = W - 30, bed = TOP + H - 3, maxLayers = 30;
    d.fillRect(left, TOP, 3, H - 1, SSD1306_WHITE);                         // frame
    d.fillRect(right - 3, TOP, 3, H - 1, SSD1306_WHITE);
    d.fillRect(left, TOP, right - left, 2, SSD1306_WHITE);
    d.drawFastHLine(left - 4, bed + 1, right - left + 8, SSD1306_WHITE);   // bed
    d.drawFastHLine(left - 4, bed + 2, right - left + 8, SSD1306_WHITE);
    unsigned long cycle = ms % ((maxLayers + 12) * 260UL);
    int layers = cycle / 260;
    if (layers > maxLayers) layers = maxLayers;                             // admire it, then restart
    int cx = W / 2;
    for (int L = 0; L < layers; L++) {
        int w = 14 + (int)(7 * sinf(L * 0.21f + 0.6f));
        d.drawFastHLine(cx - w / 2, bed - L, w, SSD1306_WHITE);
    }
    int curW = 14 + (int)(7 * sinf(layers * 0.21f + 0.6f));
    int nx = layers < maxLayers ? cx + (int)(curW / 2 * sinf(ms / 90.0f)) : cx;
    int ny = bed - layers - 2;
    d.drawFastHLine(left + 3, ny - 6, right - left - 6, SSD1306_WHITE);    // gantry
    d.fillRect(nx - 4, ny - 9, 9, 5, SSD1306_WHITE);                        // hot end
    d.fillTriangle(nx - 2, ny - 4, nx + 2, ny - 4, nx, ny - 1, SSD1306_WHITE);
}

// --- writing: a page filling up ---------------------------------------------
inline void write(Adafruit_SSD1306 &d, unsigned long ms) {
    const int px = 30, pw = W - 60, lines = 5, lineMs = 1500;
    d.drawRect(px, TOP + 1, pw, H - 1, SSD1306_WHITE);
    d.fillTriangle(px + pw - 8, TOP + 1, px + pw - 1, TOP + 1, px + pw - 1, TOP + 8, SSD1306_BLACK);
    d.drawLine(px + pw - 8, TOP + 1, px + pw - 1, TOP + 8, SSD1306_WHITE); // folded corner
    d.drawFastVLine(px + pw - 8, TOP + 1, 8, SSD1306_WHITE);
    d.drawFastHLine(px + pw - 8, TOP + 8, 8, SSD1306_WHITE);
    unsigned long n = ms / lineMs;
    int page = n / (lines + 1), onPage = n % (lines + 1);                  // one blank beat per page
    int typed = (int)((ms % lineMs) * (pw - 14) / (lineMs - 300));
    for (int l = 0; l < lines && l <= onPage; l++) {
        int y = TOP + 12 + l * 7;                                            // below the fold
        uint32_t seed = page * 10 + l;
        if (l < onPage) wordBars(d, px + 5, y, pw - 14, seed, 999, 2);
        else {
            int endX = wordBars(d, px + 5, y, pw - 14, seed, typed, 2);
            if ((ms / 300) % 2) d.drawFastVLine(endX + 2, y - 2, 6, SSD1306_WHITE);
        }
    }
}

} // namespace Scenes
