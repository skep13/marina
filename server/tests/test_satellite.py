"""The Wyoming server should take a satellite's utterance to Whisper and
send her voice back, as TECHO5's client asks for them."""
import io
import json
import socket
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process import satellite

heard = {}


def fake_transcribe(audio):
    heard["audio"] = audio
    return "what time is it"


def fake_synthesize(text):
    heard["text"] = text
    buf = io.BytesIO()
    sf.write(buf, np.zeros(24000 * 3 // 2, dtype=np.float32), 24000,
             format="WAV", subtype="PCM_16")
    return buf.getvalue(), []


def start():
    server = satellite.serve(fake_transcribe, fake_synthesize, host="127.0.0.1", port=0)
    return server, server.server_address[1]


def send(sock, typ, data=None, payload=b""):
    body = json.dumps(data).encode() if data else b""
    head = {"type": typ, "data_length": len(body), "payload_length": len(payload)}
    sock.sendall(json.dumps(head).encode() + b"\n" + body + payload)


def recv(r):
    head = json.loads(r.readline())
    data = dict(head.get("data") or {})
    if head.get("data_length"):
        data.update(json.loads(r.read(head["data_length"])))
    payload = r.read(head["payload_length"]) if head.get("payload_length") else b""
    return head["type"], data, payload


def test_transcribes_an_utterance():
    server, port = start()
    try:
        mic = {"rate": 16000, "width": 2, "channels": 1}
        with socket.create_connection(("127.0.0.1", port)) as s:
            r = s.makefile("rb")
            send(s, "transcribe", {"language": "en"})
            send(s, "audio-start", mic)
            for _ in range(4):
                send(s, "audio-chunk", mic, b"\x00\x10" * 8000)  # half a second each
            send(s, "audio-stop")
            typ, data, _ = recv(r)
        assert (typ, data["text"]) == ("transcript", "what time is it")
        audio = heard["audio"]
        assert audio.dtype == np.float32 and len(audio) == 32000
        assert abs(audio[0] - 0x1000 / 32768) < 1e-6
    finally:
        server.shutdown()


def test_speaks_in_her_voice():
    server, port = start()
    try:
        with socket.create_connection(("127.0.0.1", port)) as s:
            r = s.makefile("rb")
            send(s, "synthesize", {"text": "It's three o'clock."})
            events, pcm = [], b""
            while True:
                typ, data, payload = recv(r)
                events.append(typ)
                if typ == "audio-start":
                    assert data == {"rate": 24000, "width": 2, "channels": 1}
                pcm += payload
                if typ == "audio-stop":
                    break
        assert heard["text"] == "It's three o'clock."
        assert events == ["audio-start", "audio-chunk", "audio-chunk", "audio-stop"]
        assert len(pcm) == 24000 * 3 // 2 * 2
    finally:
        server.shutdown()


def test_describes_itself():
    server, port = start()
    try:
        with socket.create_connection(("127.0.0.1", port)) as s:
            send(s, "describe")
            typ, data, _ = recv(s.makefile("rb"))
        assert typ == "info"
        assert data["tts"][0]["voices"][0]["name"] == "marina"
        assert data["asr"][0]["installed"]
    finally:
        server.shutdown()


def test_resamples_stereo_to_whisper():
    pcm = (np.ones(4800 * 2, dtype="<i2") * 16384).tobytes()  # 0.1 s, 48 kHz stereo
    audio = satellite.to_whisper(pcm, 48000, 2, 2)
    assert len(audio) == 1600 and abs(audio.mean() - 0.5) < 1e-3
