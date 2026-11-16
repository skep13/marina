"""Marina's ear on the Drop In.

Listens to what the Echo Dot hears (PulseAudio's dot_ear.monitor), waits for
her name, and answers down the call (dot_mouth). The words go through her
own Whisper and Kokoro on the bridge's Wyoming server, and her answer comes
from the bridge's /v1/ API as model "marina-voice".

What the Dot hears is transcribed and thrown away unless it is said to her;
only what follows her name is printed or sent on.

    MARINA_BRIDGE=http://192.168.1.73:8765 MARINA_SPEECH=192.168.1.73:10300 \
        MARINA_KEY=... python3 dot_ear.py
"""
import json
import math
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from collections import deque

import numpy as np

BRIDGE = os.environ.get("MARINA_BRIDGE", "http://192.168.1.73:8765").rstrip("/")
SPEECH = os.environ.get("MARINA_SPEECH", "192.168.1.73:10300")
KEY = os.environ.get("MARINA_KEY", "")
WAKE = [w.strip().lower() for w in os.environ.get("MARINA_WAKE", "marina").split(",") if w.strip()]
EAR = os.environ.get("DOT_EAR", "dot_ear.monitor")
MOUTH = os.environ.get("DOT_MOUTH", "dot_mouth")

# DOT_DEBUG=1 logs every utterance's loudness and what Whisper made of it,
# said to her or not. For setting up only: it prints what the room says.
DEBUG = os.environ.get("DOT_DEBUG") == "1"

RATE = 16000
FRAME = int(RATE * 0.03)
MAX_UTTERANCE = 12      # seconds; longer is the telly, not someone talking to her
FOLLOW_UP = 7           # seconds she listens without her name after asking something
HISTORY = 6             # exchanges kept for a follow-up
HISTORY_TTL = 300       # seconds before a new conversation starts


def log(*a):
    print(*a, flush=True)


class VAD:
    """Speech starts when the level stays `margin_db` above a noise floor
    taken from the last few seconds, and ends after `silence_ms` below it.
    The same idea as the bridge's barge-in VAD."""

    def __init__(self, margin_db=9.0, speech_ms=240, silence_ms=700, window_s=3.0):
        self.margin = margin_db
        self.speech = max(1, int(speech_ms / 30))
        self.silence = max(1, int(silence_ms / 30))
        self.window = deque(maxlen=int(window_s / 0.03))
        self.speaking, self.score, self.below = False, 0.0, 0

    def update(self, frame):
        rms = float(np.sqrt(np.mean(np.square(frame, dtype="float64")) + 1e-12))
        db = 20 * math.log10(rms + 1e-9)
        if len(self.window) < self.window.maxlen // 3:
            self.window.append(db)
            return None
        floor = sorted(self.window)[int(len(self.window) * 0.6)]
        loud = db > floor + self.margin
        if not loud and not self.speaking:
            self.window.append(db)
        self.score = max(0.0, self.score + (1.0 if loud else -0.6))
        self.below = 0 if loud else self.below + 1
        if not self.speaking and self.score >= self.speech:
            self.speaking, self.score = True, 0.0
            return "start"
        if self.speaking and self.below >= self.silence:
            self.speaking, self.score = False, 0.0
            return "end"
        return None


_CALLS = r"(?:(?:hey|hi|ok|okay|oi|yo)[\s,]+)?"


def wake_match(text, words=WAKE):
    """The request in `text` if it is said to her (possibly empty), else
    None. Her name starts the sentence ("Marina, what time is it") or ends it
    after a comma ("what time is it, Marina")."""
    for word in words:
        name = re.escape(word)
        m = re.match(rf"\s*{_CALLS}{name}\b[\s,.!?:;-]*", text.lower())
        if m:
            return text[m.end():].strip(" ,.!?:;-")
        m = re.search(rf",\s*{name}[\s.!?]*$", text.lower())
        if m:
            return text[:m.start()].strip(" ,.!?:;-")
    return None


# Wyoming: a line of JSON, then the data as more JSON, then raw audio.

def _send(sock, typ, data=None, payload=b""):
    body = json.dumps(data).encode() if data else b""
    head = {"type": typ, "data_length": len(body), "payload_length": len(payload)}
    sock.sendall(json.dumps(head).encode() + b"\n" + body + payload)


def _recv(r):
    head = json.loads(r.readline() or b"{}")
    if not head:
        raise ConnectionError("speech server closed the connection")
    data = dict(head.get("data") or {})
    if head.get("data_length"):
        data.update(json.loads(r.read(head["data_length"])))
    payload = r.read(head["payload_length"]) if head.get("payload_length") else b""
    return head.get("type"), data, payload


def _speech_conn():
    host, port = SPEECH.rsplit(":", 1)
    sock = socket.create_connection((host, int(port)), timeout=30)
    return sock, sock.makefile("rb")


def transcribe(pcm):
    mic = {"rate": RATE, "width": 2, "channels": 1}
    sock, r = _speech_conn()
    with sock:
        _send(sock, "transcribe", {"language": "en"})
        _send(sock, "audio-start", mic)
        for i in range(0, len(pcm), 8192):
            _send(sock, "audio-chunk", mic, pcm[i:i + 8192])
        _send(sock, "audio-stop")
        while True:
            typ, data, _ = _recv(r)
            if typ == "transcript":
                return (data.get("text") or "").strip()
            if typ == "error":
                raise RuntimeError(data.get("text"))


def synthesize(text):
    sock, r = _speech_conn()
    with sock:
        _send(sock, "synthesize", {"text": text})
        rate, pcm = 24000, bytearray()
        while True:
            typ, data, payload = _recv(r)
            if typ == "audio-start":
                rate = int(data.get("rate") or rate)
            elif typ == "audio-chunk":
                pcm.extend(payload)
            elif typ == "audio-stop":
                return bytes(pcm), rate
            elif typ == "error":
                raise RuntimeError(data.get("text"))


def ask(history, text):
    body = {"model": "marina-voice",
            "messages": history + [{"role": "user", "content": text}]}
    req = urllib.request.Request(f"{BRIDGE}/v1/chat/completions",
                                 data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {KEY}"} if KEY else {})})
    with urllib.request.urlopen(req, timeout=120) as resp:
        out = json.load(resp)
    return (out["choices"][0]["message"]["content"] or "").strip()


def say(pcm, rate):
    """Into the call. Blocks until it has played."""
    subprocess.run(["pacat", "--playback", f"--device={MOUTH}", "--format=s16le",
                    f"--rate={rate}", "--channels=1", "--latency-msec=60"],
                   input=pcm, check=False)


def listen():
    """Utterances from the Dot, as 16 kHz 16-bit mono bytes."""
    proc = subprocess.Popen(["parec", f"--device={EAR}", "--format=s16le", f"--rate={RATE}",
                             "--channels=1", "--latency-msec=120"],
                            stdout=subprocess.PIPE)
    vad, heard, pre = VAD(), None, deque(maxlen=10)  # 0.3 s from before it started
    try:
        while True:
            raw = proc.stdout.read(FRAME * 2)
            if len(raw) < FRAME * 2:
                raise ConnectionError("parec stopped")
            frame = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            event = vad.update(frame)
            if heard is None:
                pre.append(raw)
                if event == "start":
                    heard = bytearray(b"".join(pre))
                continue
            heard.extend(raw)
            if event == "end" or len(heard) > MAX_UTTERANCE * RATE * 2:
                yield bytes(heard)
                heard = None
                pre.clear()
                # What was heard while she was busy answering (her own voice
                # among it) is dropped; listening starts again from now.
                fd = proc.stdout.fileno()
                os.set_blocking(fd, False)
                try:
                    while os.read(fd, 65536):
                        pass
                except BlockingIOError:
                    pass
                finally:
                    os.set_blocking(fd, True)
    finally:
        proc.kill()


def main():
    log(f"[dot] listening for {', '.join(WAKE)}; bridge {BRIDGE}, speech {SPEECH}")
    history, last_turn, open_until = [], 0.0, 0.0
    for pcm in listen():
        try:
            text = transcribe(pcm)
        except Exception as e:
            log(f"[dot] transcribing failed: {type(e).__name__}: {e}")
            continue
        if DEBUG:
            a = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
            log(f"[dot] (debug) {len(a) / RATE:.1f}s, rms {int(np.sqrt((a ** 2).mean()))}: {text!r}")
        if not text:
            continue
        now = time.time()
        request = wake_match(text)
        if request is None:
            if now > open_until:
                continue  # not said to her; dropped unread
            request = text
        if not request:
            # Just her name: whatever comes next is for her.
            open_until = now + FOLLOW_UP
            log("[dot] (her name)")
            continue
        if now - last_turn > HISTORY_TTL:
            history = []
        log(f"[dot] you: {request}")
        try:
            reply = ask(history, request)
            if not reply:
                open_until = 0
                continue
            log(f"[dot] marina: {reply}")
            say(*synthesize(reply))
        except Exception as e:
            log(f"[dot] answering failed: {type(e).__name__}: {e}")
            continue
        history = (history + [{"role": "user", "content": request},
                              {"role": "assistant", "content": reply}])[-2 * HISTORY:]
        last_turn = time.time()
        open_until = last_turn + FOLLOW_UP if reply.rstrip().endswith("?") else 0


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
