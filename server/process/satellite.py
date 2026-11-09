"""Her ears and voice for a speaker somewhere else in the house.

A Wyoming server (the protocol Home Assistant's speech servers speak), so a
voice satellite like an Echo Dot running TECHO5 can send what it hears to her
Whisper and play back her Kokoro voice. The words in between go to the /v1/
API as model "marina-voice" (see openai_api).

One port does both: give the satellite the same host:port for speech to text
and text to speech. Turned on by `satellite.enabled`. Wyoming has no keys, so
`satellite.allow` can list the addresses that may use it.

An event is a line of JSON (its type, and the lengths of what follows), then
the data as more JSON, then the payload as raw audio.
"""
import io
import json
import socketserver
import threading

import numpy as np

from process.config import load_config

_cfg = load_config().get("satellite") or {}

ENABLED = bool(_cfg.get("enabled", False))
HOST = str(_cfg.get("host") or "0.0.0.0")
PORT = int(_cfg.get("port", 10300))
ALLOW = {str(a).strip() for a in (_cfg.get("allow") or []) if str(a).strip()}

# Anything bigger is not a satellite talking.
MAX_LINE = 64 * 1024
MAX_BODY = 8 << 20
MAX_SECONDS = 30
RATE = 16000

_ABOUT = {"name": "Marina", "url": "https://github.com/skep13/marina"}

_ears_lock = threading.Lock()


def _info():
    return {
        "asr": [{
            "name": "marina-whisper", "description": "Marina's ears (Faster-Whisper)",
            "attribution": _ABOUT, "installed": True, "version": "1",
            "models": [{"name": "marina", "description": "Faster-Whisper",
                        "attribution": _ABOUT, "installed": True, "version": "1",
                        "languages": ["en"]}],
        }],
        "tts": [{
            "name": "marina-kokoro", "description": "Marina's voice (Kokoro)",
            "attribution": _ABOUT, "installed": True, "version": "1",
            "voices": [{"name": "marina", "description": "Marina",
                        "attribution": _ABOUT, "installed": True, "version": "1",
                        "languages": ["en"]}],
        }],
    }


class _Closed(Exception):
    pass


def _read_event(r):
    line = r.readline(MAX_LINE + 1)
    if not line:
        raise _Closed()
    if len(line) > MAX_LINE or not line.endswith(b"\n"):
        raise ValueError("header too long")
    header = json.loads(line)
    data = dict(header.get("data") or {})
    data_len = int(header.get("data_length") or 0)
    payload_len = int(header.get("payload_length") or 0)
    if not (0 <= data_len <= MAX_BODY and 0 <= payload_len <= MAX_BODY):
        raise ValueError("event too large")
    if data_len:
        data.update(json.loads(_read_exact(r, data_len)))
    payload = _read_exact(r, payload_len) if payload_len else b""
    return header.get("type", ""), data, payload


def _read_exact(r, n):
    got = r.read(n)
    if len(got) != n:
        raise _Closed()
    return got


def _send(w, typ, data=None, payload=b""):
    body = json.dumps(data).encode() if data else b""
    header = {"type": typ, "version": "1.0.0", "data_length": len(body),
              "payload_length": len(payload)}
    w.write(json.dumps(header).encode() + b"\n" + body + payload)
    w.flush()


def to_whisper(pcm, rate, width, channels):
    """Raw 16-bit PCM in whatever rate and channels, as Whisper's 16 kHz mono
    float32."""
    if width != 2 or not pcm:
        return np.zeros(0, dtype=np.float32)
    audio = np.frombuffer(pcm[:len(pcm) - len(pcm) % (2 * channels)], dtype="<i2")
    audio = audio.astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate and rate != RATE and len(audio):
        n = int(len(audio) * RATE / rate)
        audio = np.interp(np.linspace(0, len(audio) - 1, n),
                          np.arange(len(audio)), audio).astype(np.float32)
    return audio


def from_wav(wav):
    """Kokoro's WAV as (16-bit mono PCM bytes, rate)."""
    import soundfile as sf

    audio, rate = sf.read(io.BytesIO(wav), dtype="int16", always_2d=True)
    return audio.mean(axis=1).astype("<i2").tobytes(), rate


def _handler(transcribe, synthesize):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            client = self.client_address[0]
            if ALLOW and client not in ALLOW:
                print(f"[satellite] refused {client}: not in satellite.allow", flush=True)
                return
            heard, fmt = bytearray(), {"rate": RATE, "width": 2, "channels": 1}
            try:
                while True:
                    typ, data, payload = _read_event(self.rfile)
                    if typ == "describe":
                        _send(self.wfile, "info", _info())
                    elif typ in ("transcribe", "audio-start"):
                        if typ == "audio-start":
                            fmt = {k: int(data.get(k) or fmt[k]) for k in fmt}
                        heard.clear()
                    elif typ == "audio-chunk":
                        limit = MAX_SECONDS * fmt["rate"] * fmt["width"] * fmt["channels"]
                        if len(heard) + len(payload) <= limit:
                            heard.extend(payload)
                    elif typ == "audio-stop":
                        self._transcript(transcribe, bytes(heard), fmt, client)
                        heard.clear()
                    elif typ == "synthesize":
                        self._speak(synthesize, str(data.get("text") or "").strip())
            except _Closed:
                pass
            except (ValueError, OSError) as e:
                print(f"[satellite] {client}: {type(e).__name__}: {e}", flush=True)

        def _transcript(self, transcribe, pcm, fmt, client):
            audio = to_whisper(pcm, fmt["rate"], fmt["width"], fmt["channels"])
            try:
                with _ears_lock:
                    text = transcribe(audio) or ""
            except Exception as e:
                print(f"[satellite] transcribing failed: {type(e).__name__}: {e}", flush=True)
                _send(self.wfile, "error", {"text": "Transcribing failed."})
                return
            print(f"[satellite] heard from {client}: {text[:120]}", flush=True)
            _send(self.wfile, "transcript", {"text": text})

        def _speak(self, synthesize, text):
            if not text:
                _send(self.wfile, "error", {"text": "Nothing to say."})
                return
            try:
                pcm, rate = from_wav(synthesize(text)[0])
            except Exception as e:
                print(f"[satellite] speaking failed: {type(e).__name__}: {e}", flush=True)
                _send(self.wfile, "error", {"text": "Speaking failed."})
                return
            fmt = {"rate": rate, "width": 2, "channels": 1}
            _send(self.wfile, "audio-start", fmt)
            step = rate * 2  # a second at a time
            for i in range(0, len(pcm), step):
                _send(self.wfile, "audio-chunk", fmt, pcm[i:i + step])
            _send(self.wfile, "audio-stop")

    return Handler


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(transcribe, synthesize, host=HOST, port=PORT):
    """Start the server on a thread of its own and return it."""
    server = _Server((host, port), _handler(transcribe, synthesize))
    threading.Thread(target=server.serve_forever, daemon=True, name="satellite").start()
    return server


def start(transcribe, synthesize):
    """`transcribe` takes 16 kHz mono float32, `synthesize` text and gives
    (wav, visemes) as the TTS engine does."""
    if not ENABLED:
        return None
    try:
        server = serve(transcribe, synthesize)
    except OSError as e:
        print(f"[satellite] couldn't listen on {HOST}:{PORT}: {e}", flush=True)
        return None
    who = ", ".join(sorted(ALLOW)) if ALLOW else "anyone on the network"
    print(f"[satellite] Wyoming speech on {HOST}:{PORT} for {who}", flush=True)
    return server
