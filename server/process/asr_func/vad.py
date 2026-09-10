"""Deciding whether the microphone is hearing a person.

This exists so she can be interrupted. That turns out to be a harder listening
problem than push-to-talk, for one reason: while she is talking, her own voice
is coming out of the speakers and straight back into the microphone. A fixed
threshold either triggers on every word she says, or is set so high it misses
you entirely.

macOS only applies echo cancellation to apps that ask for the voice-processing
audio unit, which is not something sounddevice exposes. So instead of trying to
remove her voice from the signal, the threshold *follows* it:

  - The noise floor is a slow percentile of recent frames. When she starts
    talking the floor rises to meet her within about a second, so her own
    speech stops looking like an event and becomes the new normal.
  - Triggering needs a margin above that floor, held for a sustained run of
    frames. A person at a laptop is far closer to the microphone than the
    speakers are, so genuine speech clears the margin comfortably.

It is not perfect. On loud speakers in a small room it can still be fooled,
which is what `barge_in.margin_db` is for — and headphones make the whole
problem disappear.
"""
import math
from collections import deque


class VAD:
    """Energy-based speech detection with a floor that tracks the room.

    Frames go in one at a time; `update` returns 'start', 'end', or None.

    Measured on this machine, against her own voice played back into the mic:
    talking over her adds about +10 dB at a normal speaker level, +7 dB loud
    and +3.6 dB very loud. That is the whole budget, which is why the margin
    defaults to 8 rather than to something comfortable, and why the last of
    those three cases wants headphones or a lower `margin_db`.
    """

    def __init__(self, samplerate, frame_seconds=0.03, margin_db=8.0,
                 speech_ms=300, silence_ms=800, calibrate_ms=900,
                 window_seconds=2.5, percentile=75):
        self.frame = max(1, int(samplerate * frame_seconds))
        self.margin_db = float(margin_db)
        self.speech_frames = max(1, int((speech_ms / 1000.0) / frame_seconds))
        self.silence_frames = max(1, int((silence_ms / 1000.0) / frame_seconds))
        self.calibrate_frames = max(1, int((calibrate_ms / 1000.0) / frame_seconds))
        self.percentile = percentile

        self._window = deque(maxlen=max(4, int(window_seconds / frame_seconds)))

        self.floor = None
        self.speaking = False
        self._seen = 0
        self._score = 0.0
        self._below = 0

    @staticmethod
    def level_db(frame):
        import numpy as np

        rms = float(np.sqrt(np.mean(np.square(frame, dtype="float64")) + 1e-12))
        return 20.0 * math.log10(rms + 1e-9)

    def _refloor(self):
        ordered = sorted(self._window)
        idx = min(len(ordered) - 1,
                  int(len(ordered) * self.percentile / 100.0))
        self.floor = ordered[idx]

    def update(self, frame):
        db = self.level_db(frame)
        self._seen += 1

        calibrating = self._seen <= self.calibrate_frames
        loud = (not calibrating
                and self.floor is not None
                and db > self.floor + self.margin_db)

        if calibrating or (not loud and not self.speaking):
            self._window.append(db)
            self._refloor()

        if calibrating:
            return None

        self._score = max(0.0, self._score + (1.0 if loud else -0.6))

        if loud:
            self._below = 0
        else:
            self._below += 1

        if not self.speaking and self._score >= self.speech_frames:
            self.speaking = True
            self._score = 0.0
            return "start"

        if self.speaking and self._below >= self.silence_frames:
            self.speaking = False
            self._score = 0.0
            return "end"

        return None
