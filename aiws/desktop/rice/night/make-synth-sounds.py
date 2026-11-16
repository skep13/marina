#!/usr/bin/env python3
"""Make the "retro-synth" sound theme: soft chiptune blips for Noctalia.

Writes ~/.local/share/sounds/retro-synth/{index.theme,stereo/*.oga}. Every
sound is synthesised here (no samples), then encoded with ffmpeg.

  make-synth-sounds.py && noctalia msg config-set audio.sound_theme "'retro-synth'"
"""
import math
import os
import random
import struct
import subprocess
import tempfile
import wave

RATE = 44100
THEME = os.path.expanduser("~/.local/share/sounds/retro-synth")


def note(freq, dur, vol=0.35, wave_="pulse", attack=0.004, release=0.08):
    """One enveloped note: a soft pulse (square with rounded edges) or sine."""
    n = int(RATE * dur)
    out = []
    for i in range(n):
        t = i / RATE
        phase = (freq * t) % 1.0
        if wave_ == "sine":
            s = math.sin(2 * math.pi * phase)
        else:                                     # band-limited-ish pulse: square through tanh
            s = math.tanh(4 * math.sin(2 * math.pi * phase)) * 0.8
        env = min(1.0, t / attack) * min(1.0, (dur - t) / release) if dur > release else 1.0
        out.append(s * vol * max(0.0, env))
    return out


def silence(dur):
    return [0.0] * int(RATE * dur)


def noise(dur, vol=0.25):
    n = int(RATE * dur)
    return [(random.random() * 2 - 1) * vol * (1 - i / n) ** 3 for i in range(n)]


def echo(samples, delay=0.11, gain=0.3):
    d = int(RATE * delay)
    out = samples + [0.0] * d
    for i, s in enumerate(samples):
        out[i + d] += s * gain
    return out


def save(name, samples):
    os.makedirs(os.path.join(THEME, "stereo"), exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        path = tmp.name
    with wave.open(path, "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32000)) for s in samples))
    out = os.path.join(THEME, "stereo", name + ".oga")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", path, "-ac", "2",
                    "-c:a", "libvorbis", "-q:a", "5", out], check=True)
    os.remove(path)
    print("wrote", out)


E5, G5, B5, C5, C6, E6, A4 = 659.25, 783.99, 987.77, 523.25, 1046.5, 1318.5, 440.0

save("message-new-instant", echo(note(E5, 0.07) + note(B5, 0.16, release=0.12)))
save("message", echo(note(E5, 0.07) + note(B5, 0.16, release=0.12)))
save("audio-volume-change", note(C6, 0.035, vol=0.25, wave_="sine", release=0.025))
save("power-plug", echo(note(C5, 0.06) + note(E5, 0.06) + note(G5, 0.06) + note(C6, 0.18, release=0.14)))
save("power-unplug", echo(note(C6, 0.06) + note(G5, 0.06) + note(E5, 0.06) + note(C5, 0.18, release=0.14)))
save("screen-capture", noise(0.05, 0.3) + silence(0.03) + note(E6, 0.03, vol=0.2, wave_="sine", release=0.02))
save("bell", echo(note(A4, 0.09) + note(A4, 0.16, release=0.12)))
save("dialog-warning", echo(note(A4, 0.09) + note(A4, 0.16, release=0.12)))

with open(os.path.join(THEME, "index.theme"), "w") as f:
    f.write("[Sound Theme]\nName=Retro Synth\nComment=Soft chiptune blips\n"
            "Inherits=freedesktop\nDirectories=stereo\n\n[stereo]\nOutputProfile=stereo\n")
print("theme:", THEME)
