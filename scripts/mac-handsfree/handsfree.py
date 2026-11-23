"""Hands-free Marina on the Mac, the same way the iPhone app does it.

Listens all the time on the wireless lapel mic (BY-V) and plays her voice in
the AirPods, whatever macOS has picked as its own input and output. Each
phrase goes to her bridge on lab3 (/hear); she only answers what starts or
ends with her name, and for a few seconds after she answers you can carry on
without it.

It never listens on the AirPods' own mic: that drops them into call audio.
Without the BY-V it falls back to the MacBook's mic; without AirPods her
voice plays on the default output. Plugging either in or out is picked up
within a few seconds.

    .venv/bin/python scripts/mac-handsfree/handsfree.py
"""
import base64
import io
import json
import os
import queue
import sys
import time
import wave
from collections import deque
from pathlib import Path

import numpy as np
import requests
import sounddevice as sd

ROOT = Path(__file__).resolve().parents[2]
BRIDGE = os.environ.get("MARINA_BRIDGE", "https://lab3.tail35b6c6.ts.net")
TOKEN_FILE = Path(os.environ.get("MARINA_TOKEN_FILE", ROOT / "ios" / "bridge.token"))
MIC_NAMES = [s.strip().lower() for s in os.environ.get("MARINA_MIC", "by-v").split(",") if s.strip()]
OUT_NAMES = [s.strip().lower() for s in os.environ.get("MARINA_OUT", "airpods").split(",") if s.strip()]
FALLBACK_MIC = "macbook"

RATE = 16000
FRAME = 480                 # 30 ms
PREROLL = 10                # frames kept from before speech starts
START_FRAMES = 6            # ~180 ms over the floor to count as speech
END_FRAMES = 27             # ~800 ms of quiet ends a phrase
MAX_FRAMES = int(15 * RATE / FRAME)
MIN_FRAMES = 12             # shorter than ~360 ms is a click, not a phrase
MARGIN_DB = 10.0
FOLLOW_SECONDS = 8.0
RESCAN_SECONDS = 4.0


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def devices():
    sd._terminate(); sd._initialize()      # see devices plugged in since start
    return list(enumerate(sd.query_devices()))


def pick_mic():
    devs = [(i, d) for i, d in devices() if d["max_input_channels"] > 0]
    for want in MIC_NAMES + [FALLBACK_MIC]:
        for i, d in devs:
            if want in d["name"].lower():
                return i, d["name"]
    return None, None


def pick_out():
    devs = [(i, d) for i, d in devices() if d["max_output_channels"] > 0]
    for want in OUT_NAMES:
        for i, d in devs:
            if want in d["name"].lower():
                return i, d["name"]
    return None, "default output"


def plugged():
    """Device names as macOS sees them now, without restarting PortAudio
    (which would close the open mic)."""
    import subprocess
    try:
        return subprocess.run(["/opt/homebrew/bin/SwitchAudioSource", "-a"],
                              capture_output=True, text=True, timeout=5).stdout
    except Exception:
        return ""


def wav_bytes(samples):
    pcm = (np.clip(samples, -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def play(wav, out_dev):
    with wave.open(io.BytesIO(wav)) as w:
        rate, ch, width = w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(w.getnframes())
    dtype = {2: "<i2", 4: "<i4"}.get(width, "<i2")
    data = np.frombuffer(raw, dtype=dtype).astype("float32") / float(np.iinfo(dtype).max)
    data = data.reshape(-1, ch)
    sd.play(data, rate, device=out_dev)
    sd.wait()


class Listener:
    def __init__(self, token):
        self.token = token
        self.q = queue.Queue()
        self.follow_until = 0.0
        self.mic = self.out = None

    def _cb(self, indata, frames, t, status):
        self.q.put(indata[:, 0].copy())

    def send(self, clip):
        follow = time.time() < self.follow_until
        r = requests.post(f"{BRIDGE}/hear", params={"follow": "true"} if follow else {},
                          headers={"Authorization": f"Bearer {self.token}"},
                          files={"audio": ("phrase.wav", wav_bytes(clip), "audio/wav")},
                          stream=True, timeout=(10, 300))
        if r.status_code != 200:
            log(f"bridge said {r.status_code}: {r.text[:200]}")
            return
        answered = False
        for line in r.iter_lines(decode_unicode=True):
            if not line.strip():
                continue
            ev = json.loads(line)
            kind = ev.get("type")
            if kind == "ignored":
                return
            if kind == "wake":
                log("(she's listening)")
                self.follow_until = time.time() + FOLLOW_SECONDS
                return
            if kind == "transcript":
                log("you:", ev.get("text", ""))
            elif kind == "chunk":
                answered = True
                if ev.get("reply"):
                    log("marina:", ev["reply"])
                if ev.get("audio"):
                    play(base64.b64decode(ev["audio"]), self.out)
            elif kind == "error":
                log("error:", ev.get("message"))
        if answered:
            self.follow_until = time.time() + FOLLOW_SECONDS

    def run(self):
        while True:
            mic, mic_name = pick_mic()
            if mic is None:
                log("no mic found; waiting")
                time.sleep(RESCAN_SECONDS)
                continue
            self.out, out_name = pick_out()
            self.mic = mic
            log(f"listening on {mic_name}, her voice to {out_name}")
            try:
                self._listen(mic_name, out_name)
            except sd.PortAudioError as e:
                log("audio device went away:", e)
                time.sleep(1)

    def _listen(self, mic_name, out_name):
        floor = None
        pre = deque(maxlen=PREROLL)
        phrase, loud, quiet, speaking = [], 0, 0, False
        last_scan = time.time()
        seen = plugged()
        with sd.InputStream(device=self.mic, channels=1, samplerate=RATE,
                            blocksize=FRAME, dtype="float32", callback=self._cb):
            while True:
                try:
                    frame = self.q.get(timeout=1)
                except queue.Empty:
                    frame = None
                if not speaking and time.time() - last_scan > RESCAN_SECONDS:
                    last_scan = time.time()
                    if plugged() != seen:
                        return                       # something plugged in or out
                if frame is None:
                    continue
                db = 20 * np.log10(np.sqrt(np.mean(frame ** 2)) + 1e-9)
                if floor is None:
                    floor = db
                if not speaking:
                    # The room's noise: follow it down fast, up slowly.
                    floor = db if db < floor else floor + (db - floor) * 0.02
                    pre.append(frame)
                    loud = loud + 1 if db > floor + MARGIN_DB else 0
                    if loud >= START_FRAMES:
                        speaking, phrase, quiet = True, list(pre), 0
                    continue
                phrase.append(frame)
                quiet = quiet + 1 if db < floor + MARGIN_DB * 0.6 else 0
                if quiet >= END_FRAMES or len(phrase) >= MAX_FRAMES:
                    speaking, loud = False, 0
                    if len(phrase) - quiet >= MIN_FRAMES:
                        clip = np.concatenate(phrase)
                        try:
                            self.send(clip)
                        except requests.RequestException as e:
                            log("can't reach her bridge:", e)
                    # Don't treat what was heard while she talked as new speech.
                    with self.q.mutex:
                        self.q.queue.clear()
                    pre.clear()


def main():
    token = os.environ.get("MARINA_TOKEN") or (TOKEN_FILE.read_text().strip() if TOKEN_FILE.exists() else "")
    if not token:
        sys.exit(f"No bridge token: put it in {TOKEN_FILE} or MARINA_TOKEN.")
    Listener(token).run()


if __name__ == "__main__":
    main()
