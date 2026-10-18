#pragma once
// ============================================================
// FocusTimer - a pomodoro on the BOOT button
// ============================================================
// Hold BOOT ~1s: start / pause / resume. Double-press while paused: reset.
// Focus -> break -> focus..., every 4th break is a long one. When a phase
// ends the timer stops and waits for the next hold, so a break never
// silently runs into the next focus round.
#include <Arduino.h>
#include "songbird_config.h"

class FocusTimer {
public:
    enum Phase { Focus, Break };

    FocusTimer() { reset(); }

    void reset() {
        phase = Focus;
        round = 1;
        running = false;
        leftMs = lengthMs();
        lastTick = millis();
    }

    void toggle() {
        running = !running;
        lastTick = millis();
    }

    // Count down; true on the call where a phase finishes.
    bool tick() {
        unsigned long now = millis();
        if (!running) { lastTick = now; return false; }
        long spent = (long)(now - lastTick);
        lastTick = now;
        leftMs -= spent;
        if (leftMs > 0) return false;
        if (phase == Focus) {
            phase = Break;
        } else {
            phase = Focus;
            round++;
        }
        leftMs = lengthMs();
        running = false;
        return true;
    }

    bool isRunning() const { return running; }
    bool isFresh() const { return !running && leftMs == lengthMs(); }
    bool isPaused() const { return !running && !isFresh(); }
    bool active() const { return running || isPaused(); }
    Phase getPhase() const { return phase; }
    int getRound() const { return round; }
    bool longBreak() const { return round % 4 == 0; }

    long lengthMs() const {
        int m = phase == Focus ? PET_FOCUS_MIN : (longBreak() ? PET_LONG_BREAK_MIN : PET_BREAK_MIN);
        return (long)m * 60000L;
    }

    // "F 24:13" / "B 04:59" for the top bar
    String label() const {
        long s = (leftMs + 999) / 1000;
        if (s < 0) s = 0;
        char buf[12];
        snprintf(buf, sizeof(buf), "%c %02ld:%02ld", phase == Focus ? 'F' : 'B', s / 60, s % 60);
        return String(buf);
    }

private:
    Phase phase = Focus;
    int round = 1;
    bool running = false;
    long leftMs = 0;
    unsigned long lastTick = 0;
};
