"""Can she be interrupted, and does she stop interrupting herself?

Barge-in has one hard problem: while she is talking, her own voice is coming
out of the speakers and back into the microphone. Every case here is that
problem — her voice at three playback levels, with and without someone talking
over it.

The audio is synthesised with the real TTS rather than recorded, so the test
runs anywhere the app does, and the "echo" is her actual voice rather than a
stand-in. Playback level is modelled as plain attenuation, which is the part
that is a simplification: a room adds reflections and colouring this does not.
Treat the very-loud case as the honest edge of what energy alone can do.
"""
import io
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process.asr_func.recorder import SAMPLERATE      # noqa: E402
from process.asr_func.vad import VAD                  # noqa: E402
from process.tts_func.engine import synthesize        # noqa: E402

HER = ("I have been staring at the same transition for three days and it has "
       "started staring back at me, honestly. It is getting to be a problem.")
INTERRUPTIONS = ["okay, stop.", "wait, no.",
                 "hang on a second, that is not what I meant at all."]

# Attenuation standing in for how loud the speakers are.
NORMAL, LOUD, VERY_LOUD, ABSURD = 0.25, 0.35, 0.5, 0.8


def _mono16k(wav_bytes):
    audio, rate = sf.read(io.BytesIO(wav_bytes), dtype="float32")
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if rate != SAMPLERATE:
        import soxr
        audio = soxr.resample(audio, rate, SAMPLERATE)
    return audio


def _detect(signal):
    vad = VAD(SAMPLERATE)
    size = vad.frame
    for i in range(0, len(signal) - size, size):
        if vad.update(signal[i:i + size]) == "start":
            return round(i / SAMPLERATE, 2)
    return None


def _over(echo, voice, at=2.5):
    """Her voice through the speakers, with someone talking across it."""
    mixed = echo.copy()
    start = int(SAMPLERATE * at)
    segment = voice[:max(0, len(mixed) - start)]
    mixed[start:start + len(segment)] += segment
    return mixed


def run():
    her = _mono16k(synthesize(HER)[0])
    voices = [_mono16k(synthesize(t)[0]) for t in INTERRUPTIONS]

    cases = []   # (label, signal, should_trigger)

    # Her own voice must never read as someone interrupting her.
    for level, name in ((NORMAL, "normal"), (LOUD, "loud"),
                        (VERY_LOUD, "very loud"), (ABSURD, "absurd")):
        cases.append((f"echo only, speakers {name}", her * level, False))

    # Talking over her must stop her. Above VERY_LOUD the added energy is
    # smaller than the margin, which is what headphones are for.
    for level, name in ((NORMAL, "normal"), (LOUD, "loud")):
        for text, voice in zip(INTERRUPTIONS, voices):
            cases.append((f'"{text}" over speakers {name}',
                          _over(her * level, voice), True))

    cases.append(("quiet room, then you talk",
                  np.concatenate([np.zeros(int(SAMPLERATE * 1.5), dtype="float32"),
                                  voices[0]]), True))
    cases.append(("pure silence", np.zeros(int(SAMPLERATE * 6), dtype="float32"), False))
    cases.append(("room tone", np.random.default_rng(0)
                  .normal(0, 0.002, int(SAMPLERATE * 6)).astype("float32"), False))

    failures = []
    for label, signal, expected in cases:
        at = _detect(signal)
        if bool(at) != expected:
            failures.append(
                f"{label}: expected {'a trigger' if expected else 'no trigger'}, "
                f"got {f'one at {at}s' if at else 'none'}")

    print(f"  {len(cases)} cases, {len(failures)} failures")
    for f in failures:
        print("   FAIL", f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
