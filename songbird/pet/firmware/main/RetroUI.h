#pragma once
// ============================================================
// RetroUI - the Songbird pet's retro-futurist dress
// ============================================================
// The blue area is drawn as a little CRT tube (rounded bezel + scanlines),
// the clock and focus timer as leaning seven-segment digits, an atomic-age
// starburst badge sits in the yellow strip, song progress is a segmented LED bar,
// and boot gets a console-style splash.
#include <Adafruit_SSD1306.h>
#include "Config.h"

namespace RetroUI {

static const int SEG_W = 7, SEG_H = 13, SEG_T = 2;   // one digit, in pixels
static const int BEZEL_R = 7;

// --- CRT tube over the blue area -----------------------------------------
inline void crt(Adafruit_SSD1306 &d) {
    const int h = EYES_ZONE_HEIGHT;
    for (int y = EYES_ZONE_Y + 2; y < EYES_ZONE_Y + h; y += 3)       // scanlines
        d.drawFastHLine(0, y, SCREEN_WIDTH, SSD1306_BLACK);
    // black out past the rounded corners, then draw the bezel
    for (int y = 0; y < BEZEL_R; y++) {
        for (int x = 0; x < BEZEL_R; x++) {
            int dx = BEZEL_R - x, dy = BEZEL_R - y;
            if (dx * dx + dy * dy > BEZEL_R * BEZEL_R) {
                d.drawPixel(x, EYES_ZONE_Y + y, SSD1306_BLACK);
                d.drawPixel(SCREEN_WIDTH - 1 - x, EYES_ZONE_Y + y, SSD1306_BLACK);
                d.drawPixel(x, EYES_ZONE_Y + h - 1 - y, SSD1306_BLACK);
                d.drawPixel(SCREEN_WIDTH - 1 - x, EYES_ZONE_Y + h - 1 - y, SSD1306_BLACK);
            }
        }
    }
    d.drawRoundRect(0, EYES_ZONE_Y, SCREEN_WIDTH, h, BEZEL_R, SSD1306_WHITE);
}

// --- seven-segment digits, leaned forward ---------------------------------
static const int SEG_SKEW = 3;     // top of a digit sits this many px right of its foot

// One segment: a w x h block whose rows shift right with height (italic)
inline void segBlock(Adafruit_SSD1306 &d, int x, int y, int w, int h, int digitTop) {
    for (int j = 0; j < h; j++) {
        int row = y + j - digitTop;
        int off = SEG_SKEW * (SEG_H - 1 - row) / (SEG_H - 1);
        d.drawFastHLine(x + off, y + j, w, SSD1306_WHITE);
    }
}

inline void segDigit(Adafruit_SSD1306 &d, int x, int y, char ch) {
    // segments a b c d e f g as bits 0..6
    static const uint8_t MAP[10] = {0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07, 0x7F, 0x6F};
    uint8_t on = (ch >= '0' && ch <= '9') ? MAP[ch - '0'] : (ch == '-' ? 0x40 : 0);
    const int m = (SEG_H - SEG_T) / 2;
    const int lower = SEG_H - m - SEG_T - 1;
    if (on & 0x01) segBlock(d, x + 1, y, SEG_W - 2, SEG_T, y);                       // a
    if (on & 0x02) segBlock(d, x + SEG_W - SEG_T, y + 1, SEG_T, m - 1, y);           // b
    if (on & 0x04) segBlock(d, x + SEG_W - SEG_T, y + m + SEG_T, SEG_T, lower, y);   // c
    if (on & 0x08) segBlock(d, x + 1, y + SEG_H - SEG_T, SEG_W - 2, SEG_T, y);       // d
    if (on & 0x10) segBlock(d, x, y + m + SEG_T, SEG_T, lower, y);                   // e
    if (on & 0x20) segBlock(d, x, y + 1, SEG_T, m - 1, y);                           // f
    if (on & 0x40) segBlock(d, x + 1, y + m, SEG_W - 2, SEG_T, y);                   // g
}

// Width of "23:46"-style text in segment digits (including the lean).
inline int segWidth(const char *s) {
    int w = 0;
    for (; *s; s++) w += (*s == ':') ? SEG_T + 2 : SEG_W + 2;
    return w > 0 ? w - 2 + SEG_SKEW : 0;
}

inline void segText(Adafruit_SSD1306 &d, int x, int y, const char *s, bool colonOn = true) {
    for (; *s; s++) {
        if (*s == ':') {
            if (colonOn) {
                segBlock(d, x, y + 3, SEG_T, SEG_T, y);
                segBlock(d, x, y + SEG_H - 5, SEG_T, SEG_T, y);
            }
            x += SEG_T + 2;
        } else {
            segDigit(d, x, y, *s);
            x += SEG_W + 2;
        }
    }
}

// --- atomic-age starburst badge (13x13) ---------------------------------
// The Googie "sparkle" from 50s/60s world-of-tomorrow design. It twinkles
// now and then: the long rays pull in for a moment.
inline void starburst(Adafruit_SSD1306 &d, int x, int y, bool twinkle = false) {
    static const char *FULL[13] = {
        "......X......",
        "......X......",
        ".....XXX.....",
        "..X..XXX..X..",
        "...X.XXX.X...",
        "....XXXXX....",
        "XXXXXXXXXXXXX",
        "....XXXXX....",
        "...X.XXX.X...",
        "..X..XXX..X..",
        ".....XXX.....",
        "......X......",
        "......X......",
    };
    static const char *SMALL[13] = {
        ".............",
        ".............",
        "......X......",
        "......X......",
        "....X.X.X....",
        ".....XXX.....",
        "..XXXXXXXXX..",
        ".....XXX.....",
        "....X.X.X....",
        "......X......",
        "......X......",
        ".............",
        ".............",
    };
    const char **rows = twinkle ? SMALL : FULL;
    for (int j = 0; j < 13; j++)
        for (int i = 0; i < 13; i++)
            if (rows[j][i] == 'X') d.drawPixel(x + i, y + j, SSD1306_WHITE);
}

// Twinkles for 300ms every ~3.5s
inline bool starTwinkle() { return (millis() % 3500) < 300; }

// --- segmented LED bar ---------------------------------------------------
inline void ledBar(Adafruit_SSD1306 &d, int y, float frac) {
    if (frac < 0) frac = 0;
    if (frac > 1) frac = 1;
    const int n = SCREEN_WIDTH / 4;
    int lit = (int)(n * frac + 0.5f);
    for (int i = 0; i < n; i++) {
        if (i < lit) d.fillRect(i * 4, y, 3, 2, SSD1306_WHITE);
        else d.drawPixel(i * 4 + 1, y + 1, SSD1306_WHITE);
    }
}

// --- boot splash -----------------------------------------------------------
inline void splash(Adafruit_SSD1306 &d) {
    d.clearDisplay();
    d.drawRoundRect(0, EYES_ZONE_Y, SCREEN_WIDTH, EYES_ZONE_HEIGHT, BEZEL_R, SSD1306_WHITE);
    starburst(d, (SCREEN_WIDTH - 13) / 2, EYES_ZONE_Y + 3);
    d.setTextWrap(false);
    d.setTextColor(SSD1306_WHITE);
    d.setTextSize(2);
    d.setCursor((SCREEN_WIDTH - 8 * 12) / 2, EYES_ZONE_Y + 17);
    d.print("SONGBIRD");
    d.setTextSize(1);
    d.setCursor((SCREEN_WIDTH - 14 * 6) / 2, EYES_ZONE_Y + 37);
    d.print("SYSTEMS ONLINE");
    for (int y = EYES_ZONE_Y + 2; y < EYES_ZONE_Y + EYES_ZONE_HEIGHT - 1; y += 3)
        d.drawFastHLine(1, y, SCREEN_WIDTH - 2, SSD1306_BLACK);
    for (int i = 0; i < 10; i++) d.fillRect(4 + i * 12, TEXT_ZONE_Y + 6, 10, 4, SSD1306_WHITE);
    d.display();
}

} // namespace RetroUI
