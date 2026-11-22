"""HTTP bridge between the desktop app and the ASR / LLM / TTS pipeline.

    python server/marina_server.py
"""
import base64
import hmac
import json
import queue
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "server"))

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from openai import APIConnectionError
from pydantic import BaseModel

from process.asr_func.asr_push_to_talk import build_model, transcribe_audio, transcribe_file
from process.asr_func.listen import Ear, wake_match
from process.asr_func.recorder import Recorder
from process.asr_func.vad import VAD
from process.config import CONFIG_PATH, load_config
from process.llm_funcs.llm_scr import (
    Activity,
    active_endpoint,
    active_model,
    append_local,
    describe_endpoint,
    load_local_history,
    reset_local_history,
    llm_response,
    llm_stream,
    note_exchange,
    reset_history,
    save_turn,
)
from process.tts_func.engine import (
    TTSError,
    describe as describe_tts,
    kokoro_voices,
    synthesize,
)
from process.tts_func.engine import warmup as warmup_tts
from process.text_func.speech import SentenceSplitter, split_reply
from process import backend
from process import confirm
from process import openai_api
from process import shared
from process import config as cfg
from process import idle
from process import call
from process import notice
from process import push
from process import mood as her_mood
from process import state as her_state
from process import ratings
from process.tools import registry as tools
from process.memory import store as memory
from process.vision.look import (
    ENABLED as VISION_ENABLED,
    MODEL as VISION_MODEL,
    VisionError,
    describe as describe_screen,
)

config = load_config()

app = FastAPI(title="Marina bridge")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_whisper = None
recorder = Recorder()


def whisper():
    """Load Whisper on first use."""
    global _whisper
    if _whisper is None:
        print("Loading Faster-Whisper...", flush=True)
        _whisper = build_model()
        print("Faster-Whisper ready.", flush=True)
    return _whisper


class ChatIn(BaseModel):
    text: str
    speak: bool = True


def llm_error_message(e):
    msg = getattr(getattr(e, "response", None), "text", "") or str(e)
    if "invalid_api_key" in msg or "Incorrect API key" in msg:
        return f"That API key was rejected. Set llm.api_key in {CONFIG_PATH}."
    if "rate_limit" in msg or "429" in msg:
        return "The endpoint rate-limited the request. Wait a moment and try again."
    if isinstance(e, APIConnectionError) or "Connection" in type(e).__name__:
        if backend.mode() == "auto" and len(backend.BACKENDS) > 1:
            tried = ", ".join(f"{b['label']} ({b['base_url'] or 'OpenAI'})"
                              for b in backend.BACKENDS)
            return f"None of Marina's brains answered. Tried {tried}."
        return (
            f"No language model answered at {describe_endpoint()}. Marina needs "
            "one to talk. Install Ollama and run 'ollama pull llama3.2:3b', or "
            f"point llm.base_url at any OpenAI-compatible server in {CONFIG_PATH}."
        )
    return f"LLM call failed: {type(e).__name__}: {str(e)[:200]}"


def _respond(user_text, speak, transcript=None):
    out = {"transcript": transcript if transcript is not None else user_text,
           "reply": "",
           "speech": "",
           "cues": [],
           "audio": None,
           "error": None}

    try:
        reply = llm_response(user_text)
    except Exception as e:
        out["error"] = llm_error_message(e)
        print(f"[llm] {out['error']}", flush=True)
        return out

    parts = split_reply(reply)
    out["reply"] = parts["display"]
    out["speech"] = parts["speech"]
    out["backend"] = active_endpoint()
    out["model"] = active_model()
    out["cues"] = parts["cues"]

    if not speak:
        return out

    try:
        if out["speech"]:
            wav, visemes = synthesize(out["speech"])
            out["audio"] = base64.b64encode(wav).decode("ascii")
            out["visemes"] = visemes
    except TTSError as e:
        out["error"] = str(e)
        print(f"[tts] {e}", flush=True)

    return out


@app.get("/health")
def health():
    return {
        "ok": True,
        "model": active_model(),
        "llm_endpoint": describe_endpoint(),
        "llm_using": active_endpoint(),
        "llm_mode": backend.mode(),
        "llm_labels": backend.labels(),
        "preset": cfg.preset(),
        "tts": describe_tts(),
        "whisper_loaded": _whisper is not None,
        "recording": recorder.is_recording,
        "memories": len(memory.all_facts()),
        "vision": VISION_MODEL if VISION_ENABLED else None,
        "camera": bool(cfg.setting("tools", "camera", True)),
        "barge_in": _barge_enabled(),
        "idle": idle.status(),
        "call": call.status(),
        "workspace": _workspace_name(),
        "push": push.enabled(),
    }


def _workspace_name():
    from process.tools import workspace
    return workspace.NAME if workspace.available() else None


@app.post("/chat")
def chat(body: ChatIn):
    text = body.text.strip()
    if not text:
        return {"transcript": "", "reply": "", "speech": "", "cues": [],
                "audio": None, "error": "Empty message."}
    print(f"[you] {text}", flush=True)
    idle.note_interaction()
    result = _respond(text, body.speak)
    print(f"[marina] {result['reply']}", flush=True)
    return result


_stream = {"id": 0, "stop_at": None}
_stream_lock = threading.Lock()


def _ndjson(event):
    return json.dumps(event, ensure_ascii=False) + "\n"


def _speak_segment(segment, index, speak):
    parts = split_reply(segment)
    if parts["mood"]["name"] == "neutral":
        # Nothing in the sentence itself: her face rests on the mood she is in.
        parts["mood"] = her_mood.face() or parts["mood"]
    event = {
        "type": "chunk",
        "index": index,
        "reply": parts["display"],
        "speech": parts["speech"],
        "cues": parts["cues"],
        "mood": parts["mood"],
        "audio": None,
        "visemes": [],
        "backend": active_endpoint(),
        "model": active_model(),
    }
    if speak and parts["speech"]:
        try:
            wav, visemes = synthesize(parts["speech"])
            event["audio"] = base64.b64encode(wav).decode("ascii")
            event["visemes"] = visemes
        except TTSError as e:
            event["error"] = str(e)
            print(f"[tts] {e}", flush=True)
    return event


def _stream_reply(user_text, speak=True, transcript=None, extra_system=None,
                  record=True):
    """Stream the reply one sentence at a time, synthesizing as it goes."""
    with _stream_lock:
        _stream["id"] += 1
        _stream["stop_at"] = None
        stream_id = _stream["id"]

    def stop_after():
        with _stream_lock:
            if _stream["id"] != stream_id:
                return index
            return _stream["stop_at"]

    yield _ndjson({"type": "start", "id": stream_id,
                   "transcript": transcript if transcript is not None else user_text,
                   "unprompted": user_text is None})

    splitter = SentenceSplitter()
    spoken = []
    index = 0
    interrupted = False
    generator = llm_stream(user_text, extra_system=call.extra_for(user_text, extra_system))

    def emit(segment):
        nonlocal index
        event = _speak_segment(segment, index, speak)
        if not event["speech"] and not event["cues"]:
            return None
        spoken.append(segment)
        index += 1
        return _ndjson(event)

    try:
        try:
            for delta in generator:
                limit = stop_after()
                if limit is not None:
                    interrupted = True
                    break
                if isinstance(delta, Activity):
                    # What she is doing, and on whose computer, for the app
                    # to show; or a question for them to answer.
                    yield _ndjson({"type": "confirm" if delta.confirm else "activity",
                                   "id": delta.confirm, "where": delta.where,
                                   "text": delta.label})
                    continue
                for segment in splitter.feed(delta):
                    event = emit(segment)
                    if event:
                        yield event
            if not interrupted:
                tail = splitter.flush()
                if tail:
                    event = emit(tail)
                    if event:
                        yield event
        finally:
            generator.close()
    except Exception as e:
        message = llm_error_message(e)
        print(f"[llm] {message}", flush=True)
        if record:
            save_turn(user_text, " ".join(spoken))
        yield _ndjson({"type": "error", "message": message})
        return

    limit = stop_after()
    if limit is not None:
        interrupted = True
        heard = " ".join(spoken[:max(0, limit)]).rstrip()
        heard = (heard + " \u2014") if heard else ""
    else:
        heard = " ".join(spoken)

    if record:
        save_turn(user_text, heard)
    idle.note_interaction()

    print(f"[marina] {heard}", flush=True)
    yield _ndjson({"type": "interrupted" if interrupted else "done",
                   "chunks": index, "reply": heard})


@app.post("/chat/stream")
def chat_stream(body: ChatIn):
    text = body.text.strip()
    if not text:
        return StreamingResponse(
            iter([_ndjson({"type": "error", "message": "Empty message."})]),
            media_type="application/x-ndjson")
    print(f"[you] {text}", flush=True)
    return StreamingResponse(_stream_reply(text, body.speak),
                             media_type="application/x-ndjson")


class InterruptIn(BaseModel):
    chunks: int = 0
    stop_work: bool = False   # also kill the command she is running on her machine


@app.post("/interrupt")
def interrupt(body: InterruptIn):
    """Stop the current reply. Only the first `chunks` sentences get saved."""
    with _stream_lock:
        _stream["stop_at"] = max(0, body.chunks)
        stream_id = _stream["id"]
    confirm.cancel_all()  # stopping her is a no to anything she was asking
    if body.stop_work:
        from process.tools import workspace
        if workspace.available():
            threading.Thread(target=workspace.stop_running, daemon=True).start()
    return {"ok": True, "id": stream_id, "heard": max(0, body.chunks)}


@app.get("/workspace/screen")
def workspace_screen(full: bool = False):
    """What is on the screen of the machine she works on (lab2), for the
    app to show while she works."""
    from process.tools import workspace
    if not workspace.available():
        return JSONResponse({"error": "She has no machine to work on."}, status_code=404)
    image = workspace.screen_jpeg(full)
    if image is None:
        return JSONResponse({"error": f"Couldn't see {workspace.NAME}'s screen."}, status_code=502)
    return Response(image, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


# ---- stage: type on one device, she answers on another ------------------------
# The desktop app's "Type to her screen" window posts to /stage/say; every
# screen holding /stage/listen open (lab3's monitor kiosk) plays the reply.
# Events carry a sequence number so a screen that reconnects between polls
# picks up where it left off instead of missing the start of a reply.
_stage = {"seq": 0, "log": [], "screens": 0}
_stage_cv = threading.Condition()


def _stage_publish(event):
    with _stage_cv:
        _stage["seq"] += 1
        _stage["log"].append({**event, "seq": _stage["seq"]})
        del _stage["log"][:-300]
        _stage_cv.notify_all()


class StageIn(BaseModel):
    text: str
    speak: bool = False   # her voice on the screen (costs TTS time on this machine)


@app.post("/stage/say")
def stage_say(body: StageIn):
    text = body.text.strip()
    if not text:
        return StreamingResponse(
            iter([_ndjson({"type": "error", "message": "Empty message."})]),
            media_type="application/x-ndjson")
    print(f"[you, to the screen] {text}", flush=True)

    def relay():
        with _stage_cv:
            screens = _stage["screens"]
        yield _ndjson({"type": "screens", "count": screens})
        for line in _stream_reply(text, body.speak):
            event = json.loads(line)
            if event.get("type") == "start":
                event["transcript"] = text
            _stage_publish(event)
            # The sender only needs the words; the audio is for the screen.
            event.pop("audio", None)
            event.pop("visemes", None)
            yield _ndjson(event)

    return StreamingResponse(relay(), media_type="application/x-ndjson")


@app.get("/stage/listen")
def stage_listen(after: int = -1, timeout: float = 60.0):
    """Long poll for a screen: streams each relayed reply as it happens."""
    def stream():
        with _stage_cv:
            _stage["screens"] += 1
            last = _stage["seq"] if after < 0 else after
        try:
            yield _ndjson({"type": "ready", "seq": last})
            end = time.monotonic() + min(max(timeout, 5.0), 300.0)
            while True:
                left = end - time.monotonic()
                with _stage_cv:
                    _stage_cv.wait_for(lambda: _stage["seq"] > last, timeout=max(0.0, min(15.0, left)))
                    new = [e for e in _stage["log"] if e["seq"] > last]
                if new:
                    for event in new:
                        last = event["seq"]
                        yield _ndjson(event)
                    end = max(end, time.monotonic() + 30)   # stay open while she talks
                elif time.monotonic() >= end:
                    return
                else:
                    yield _ndjson({"type": "waiting"})       # notices a closed connection
        finally:
            with _stage_cv:
                _stage["screens"] -= 1

    return StreamingResponse(stream(), media_type="application/x-ndjson")


class ConfirmIn(BaseModel):
    id: str
    ok: bool


@app.post("/confirm")
def confirm_answer(body: ConfirmIn):
    """Their answer to something she asked before doing it on their Mac."""
    known = confirm.answer(body.id, body.ok)
    print(f"[mac] they {'allowed' if body.ok else 'refused'} it", flush=True)
    return {"ok": known}


class MacIn(BaseModel):
    enabled: bool


def _mac_status():
    from process.tools import mac
    return {"available": sys.platform == "darwin", "enabled": mac.available(),
            "screen": mac.can_see(), "control": mac.can_control()}


@app.get("/mac")
def mac_get():
    return _mac_status()


@app.post("/mac")
def mac_set(body: MacIn):
    """Let her use this Mac, or stop. Saved to the config."""
    cfg.set_value("mac", "enabled", body.enabled)
    if body.enabled:
        from process.tools import mac
        mac.ask_for_permissions()
    print(f"[mac] {'she can use this Mac' if body.enabled else 'she can no longer use this Mac'}",
          flush=True)
    return _mac_status()


@app.post("/voice")
def voice(audio: UploadFile = File(...), speak: bool = True):
    suffix = Path(audio.filename or "clip.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio.file.read())
        tmp_path = Path(tmp.name)

    try:
        transcript = transcribe_file(whisper(), tmp_path)
    finally:
        tmp_path.unlink(missing_ok=True)

    print(f"[you] {transcript}", flush=True)

    if not transcript:
        return {"transcript": "", "reply": "", "speech": "", "cues": [],
                "audio": None, "error": "Didn't catch that."}

    result = _respond(transcript, speak, transcript=transcript)
    print(f"[marina] {result['reply']}", flush=True)
    return result


@app.post("/listen/start")
def listen_start():
    threading.Thread(target=whisper, daemon=True).start()
    if recorder.is_monitoring:
        recorder.cancel()
    started = recorder.start()
    return {"ok": True, "started": started, "already_recording": not started}


@app.post("/listen/stop")
def listen_stop(speak: bool = True):
    path = recorder.stop()
    if path is None:
        return {"transcript": "", "reply": "", "speech": "", "cues": [],
                "audio": None, "error": "Nothing recorded."}

    try:
        transcript = transcribe_file(whisper(), path)
    finally:
        path.unlink(missing_ok=True)

    print(f"[you] {transcript}", flush=True)

    if not transcript:
        return {"transcript": "", "reply": "", "speech": "", "cues": [],
                "audio": None, "error": "Didn't catch that."}

    result = _respond(transcript, speak, transcript=transcript)
    print(f"[marina] {result['reply']}", flush=True)
    return result


def _stream_error(message):
    return StreamingResponse(
        iter([_ndjson({"type": "error", "message": message})]),
        media_type="application/x-ndjson")


def _stream_transcript(path):
    try:
        transcript = transcribe_file(whisper(), path)
    finally:
        path.unlink(missing_ok=True)

    if not transcript:
        return _stream_error("Didn't catch that.")

    print(f"[you] {transcript}", flush=True)
    idle.note_interaction()
    return StreamingResponse(
        _stream_reply(transcript, True, transcript=transcript),
        media_type="application/x-ndjson")


@app.post("/listen/stop/stream")
def listen_stop_stream():
    path = recorder.stop()
    if path is None:
        return _stream_error("Nothing recorded.")
    return _stream_transcript(path)


@app.post("/voice/stream")
def voice_stream(audio: UploadFile = File(...)):
    """Like /listen/stop/stream, for a clip recorded somewhere else, such as
    a phone's browser."""
    suffix = Path(audio.filename or "clip.webm").suffix or ".webm"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(audio.file.read())
    return _stream_transcript(Path(tmp.name))


def _wav_to_float(data):
    """16-bit PCM WAV bytes to 16 kHz mono float32, or None."""
    import io
    import wave

    import numpy as np

    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getsampwidth() != 2:
                return None
            channels, rate = w.getnchannels(), w.getframerate()
            pcm = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    except (wave.Error, EOFError):
        return None
    audio = pcm.astype("float32") / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != 16000 and len(audio):
        idx = np.linspace(0, len(audio) - 1, int(len(audio) * 16000 / rate))
        audio = np.interp(idx, np.arange(len(audio)), audio).astype("float32")
    return audio


@app.post("/hear")
def hear(audio: UploadFile = File(...), follow: bool = False):
    """Hands-free on the phone: one phrase the phone's mic picked up, as a
    16-bit WAV. She answers if it was said to her ("Marina, ...", "...,
    Marina?"), or straight away when `follow` says you're still talking to
    her. Anything else is dropped without a word: {"type": "ignored"}.
    Her name alone gives {"type": "wake"}, for the phone to listen on."""
    samples = _wav_to_float(audio.file.read())
    if samples is None:
        return _stream_error("That clip wasn't a 16-bit WAV.")
    with _ears_lock_hear:
        text = transcribe_audio(whisper(), samples, prompt=WAKE_PROMPT).strip()
    if not text:
        return StreamingResponse(iter([_ndjson({"type": "ignored"})]),
                                 media_type="application/x-ndjson")
    request = text if follow else wake_match(text, WAKE_WORDS)
    if request is None:
        print(f"[hear] (not to her) {text[:80]}", flush=True)
        return StreamingResponse(iter([_ndjson({"type": "ignored", "text": text})]),
                                 media_type="application/x-ndjson")
    if not request.strip(" .,!?"):
        print("[hear] her name", flush=True)
        return StreamingResponse(iter([_ndjson({"type": "wake", "text": text})]),
                                 media_type="application/x-ndjson")
    return StreamingResponse(_reply_to(request), media_type="application/x-ndjson")


_ears_lock_hear = threading.Lock()   # one Whisper run at a time from the phone


_listen_cfg = config.get("listen") or {}
LISTEN_SECONDS = float(_listen_cfg.get("max_seconds", 10))
PAUSE_MS = int(_listen_cfg.get("pause_ms", 900))

_wake_cfg = config.get("wake") or {}
WAKE_WORDS = [str(w) for w in (_wake_cfg.get("words") or ["marina"])]
WAKE_WAIT = float(_wake_cfg.get("listen_seconds", LISTEN_SECONDS))
# Whisper writes names it hasn't been told about however it likes.
WAKE_PROMPT = ", ".join(w.capitalize() for w in WAKE_WORDS[:1]) + "."

_ears = {"button": None}


def _reply_to(transcript):
    """The tail every voice path shares once it knows what was said."""
    print(f"[you] {transcript}", flush=True)
    idle.note_interaction()
    yield _ndjson({"type": "transcript", "text": transcript})
    yield from _stream_reply(transcript, True, transcript=transcript)


def _auto_stream(max_seconds):
    try:
        ear = Ear(max_seconds=max_seconds, pause_ms=PAUSE_MS).open()
    except Exception as e:
        yield _ndjson({"type": "error", "message": f"Can't open the microphone: {e}"})
        return
    _ears["button"] = ear
    audio = None
    try:
        yield _ndjson({"type": "armed", "max_seconds": max_seconds})
        while audio is None:
            try:
                event = ear.events.get(timeout=0.25)
            except queue.Empty:
                yield _ndjson({"type": "waiting"})
                continue
            if event[0] == "start":
                yield _ndjson({"type": "speech"})
            elif event[0] == "silence":
                yield _ndjson({"type": "cancelled", "message": "Didn't hear anything."})
                return
            elif event[0] == "phrase":
                audio = event[1]
    finally:
        ear.close()
        if _ears["button"] is ear:
            _ears["button"] = None

    yield _ndjson({"type": "transcribing"})
    transcript = transcribe_audio(whisper(), audio)
    if not transcript:
        yield _ndjson({"type": "cancelled", "message": "Didn't catch that."})
        return
    yield from _reply_to(transcript)


@app.get("/listen/auto")
def listen_auto(max_seconds: float = 0):
    """Listen from now until you pause, `listen.max_seconds` is up, or
    /listen/finish, then reply. For the mic button."""
    threading.Thread(target=whisper, daemon=True).start()
    limit = min(max_seconds or LISTEN_SECONDS, 60.0)
    return StreamingResponse(_auto_stream(limit), media_type="application/x-ndjson")


@app.post("/listen/finish")
def listen_finish():
    ear = _ears["button"]
    if ear is not None:
        ear.finish()
    return {"ok": True, "listening": ear is not None}


def _wake_stream(timeout):
    from process.asr_func.recorder import SAMPLERATE

    vad = VAD(SAMPLERATE,
              margin_db=float(_wake_cfg.get("margin_db", 10.0)),
              speech_ms=int(_wake_cfg.get("speech_ms", 200)),
              silence_ms=int(_wake_cfg.get("silence_ms", 600)))
    try:
        ear = Ear(vad, max_seconds=max(WAKE_WAIT, 6.0)).open()
    except Exception as e:
        yield _ndjson({"type": "error", "message": f"Can't open the microphone: {e}"})
        return

    request = None
    woke_at = None
    deadline = time.time() + timeout
    try:
        yield _ndjson({"type": "armed"})
        while request is None:
            now = time.time()
            if woke_at is None and now > deadline:
                yield _ndjson({"type": "idle"})
                return
            if woke_at is not None and now > woke_at + WAKE_WAIT:
                print("[wake] nothing after her name", flush=True)
                yield _ndjson({"type": "cancelled"})
                return
            try:
                event = ear.events.get(timeout=0.25)
            except queue.Empty:
                yield _ndjson({"type": "waiting"})
                continue
            if event[0] == "start":
                if woke_at is not None:
                    yield _ndjson({"type": "speech"})
                continue
            if event[0] != "phrase":
                continue
            # Only her name or what follows it is ever printed or kept; the
            # rest of what the mic hears is transcribed and thrown away.
            text = transcribe_audio(whisper(), event[1], prompt=WAKE_PROMPT)
            if woke_at is not None:
                if text:
                    request = text
                continue
            rest = wake_match(text, WAKE_WORDS)
            if rest is None:
                continue
            print("[wake] heard her name", flush=True)
            if rest:
                request = rest
            else:
                woke_at = time.time()
                yield _ndjson({"type": "wake", "listen_seconds": WAKE_WAIT})
    finally:
        ear.close()

    yield from _reply_to(request)


@app.get("/wake/listen")
def wake_listen(timeout: float = 120.0):
    """Long poll: listens for her name. Say it with a request ("Marina, what
    time is it") and she answers; say it alone and she waits
    `wake.listen_seconds` for the rest."""
    threading.Thread(target=whisper, daemon=True).start()
    return StreamingResponse(_wake_stream(min(timeout, 600.0)),
                             media_type="application/x-ndjson")


def _drop_ear():
    """Stop a /listen/auto without transcribing anything: close the mic and
    end its stream as if nothing was said."""
    ear = _ears["button"]
    if ear is not None:
        ear.close()
        ear.events.put(("silence",))
    return ear is not None


@app.post("/listen/cancel")
def listen_cancel():
    recorder.cancel()
    dropped = _drop_ear()
    return {"ok": True, "dropped": dropped}


_barge = config.get("barge_in") or {}


def _barge_enabled():
    """Read on every call: presentation mode turns it off, since a busy room
    would keep cutting her off."""
    return bool(cfg.setting("barge_in", "enabled", True))


def _make_vad():
    from process.asr_func.recorder import SAMPLERATE

    return VAD(
        SAMPLERATE,
        margin_db=float(_barge.get("margin_db", 12.0)),
        speech_ms=int(_barge.get("speech_ms", 220)),
        silence_ms=int(_barge.get("silence_ms", 800)),
    )


def _barge_stream(timeout):
    """Listen while she talks. If the user cuts in, transcribe it and stream
    the next reply on the same connection."""
    # A barge listen whose client went away keeps the mic until it is
    # garbage collected, so a new one takes it over instead of failing.
    if recorder.is_monitoring:
        recorder.cancel()
    started = recorder.start(_make_vad())
    if not started:
        yield _ndjson({"type": "error", "message": "Microphone already in use."})
        return

    yield _ndjson({"type": "armed"})

    deadline = time.time() + timeout
    heard = False
    try:
        while True:
            if time.time() > deadline:
                return
            if not recorder.is_monitoring:
                return
            try:
                event = recorder.events.get(timeout=0.25)
            except queue.Empty:
                yield _ndjson({"type": "waiting"})
                continue

            if event == "start" and not heard:
                heard = True
                yield _ndjson({"type": "speech"})
                deadline = time.time() + 60
            elif event == "end" and heard:
                break

        path = recorder.stop(from_onset=True)
        if path is None:
            yield _ndjson({"type": "cancelled"})
            return

        try:
            transcript = transcribe_file(whisper(), path)
        finally:
            path.unlink(missing_ok=True)

        if not transcript:
            yield _ndjson({"type": "cancelled"})
            return

        print(f"[you, cutting in] {transcript}", flush=True)
        yield _ndjson({"type": "transcript", "text": transcript})
        yield from _stream_reply(transcript, True, transcript=transcript)
    finally:
        if recorder.is_monitoring:
            recorder.cancel()


@app.get("/barge/listen")
def barge_listen(timeout: float = 45.0):
    if not _barge_enabled():
        return StreamingResponse(
            iter([_ndjson({"type": "disabled"})]),
            media_type="application/x-ndjson")
    threading.Thread(target=whisper, daemon=True).start()
    return StreamingResponse(_barge_stream(timeout),
                             media_type="application/x-ndjson")


@app.post("/barge/stop")
def barge_stop():
    """The app stopped listening for interruptions: release the mic now
    rather than when the abandoned stream is collected."""
    stopped = recorder.is_monitoring
    if stopped:
        recorder.cancel()
    return {"ok": True, "stopped": stopped}


class SeeIn(BaseModel):
    image: str
    mime: str = "image/jpeg"
    question: str = ""
    speak: bool = True
    source: str = "screen"  # or "camera", a photo of them


@app.post("/see")
def see(body: SeeIn):
    camera = body.source == "camera"
    if camera and not cfg.setting("tools", "camera", True):
        return {"transcript": "", "reply": "", "speech": "", "cues": [], "audio": None,
                "error": "Looking through the camera is switched off."}
    out = {"transcript": body.question or ("(looked at you)" if camera else "(looked at the screen)"),
           "reply": "", "speech": "", "cues": [], "audio": None, "error": None}

    try:
        raw = base64.b64decode(body.image)
    except Exception:
        out["error"] = "Screenshot was not valid base64."
        return out

    print(f"[see] {len(raw)/1024:.0f} KB {'photo' if camera else 'screenshot'}", flush=True)

    try:
        answer = describe_screen(raw, body.question, body.mime,
                                 source="camera" if camera else "screen")
    except VisionError as e:
        out["error"] = str(e)
        print(f"[see] {e}", flush=True)
        return out

    parts = split_reply(answer)
    out["reply"] = parts["display"]
    out["speech"] = parts["speech"]
    out["backend"] = active_endpoint()
    out["model"] = active_model()
    out["cues"] = parts["cues"]
    print(f"[marina] {parts['speech']}", flush=True)

    if camera:
        note_exchange(body.question or "Look at me.", f"(looked at you through the camera) {answer}")
    else:
        note_exchange(body.question or "What is on my screen?",
                      f"(looked at your screen) {answer}")

    if body.speak and out["speech"]:
        try:
            wav, visemes = synthesize(out["speech"])
            out["audio"] = base64.b64encode(wav).decode("ascii")
            out["visemes"] = visemes
        except TTSError as e:
            out["error"] = str(e)

    return out


def _list_models(base_url, api_key):
    if not base_url:
        return []
    try:
        from openai import OpenAI
        c = OpenAI(api_key=api_key or "not-needed", base_url=base_url,
                   timeout=4.0, max_retries=0)
        return sorted(m.id for m in c.models.list().data)
    except Exception:
        return []


@app.get("/models")
def models_list():
    from concurrent.futures import ThreadPoolExecutor
    # Ask every backend at once, so one box that is off costs 4 seconds total
    # rather than 4 seconds each.
    with ThreadPoolExecutor(len(backend.BACKENDS)) as pool:
        found = list(pool.map(
            lambda b: _list_models(b["base_url"], b["api_key"]), backend.BACKENDS))
    out = {b["name"]: m for b, m in zip(backend.BACKENDS, found)}
    out.update({
        "backends": [{"name": b["name"], "label": b["label"], "models": m}
                     for b, m in zip(backend.BACKENDS, found)],
        "selected": backend.models(),
        "mode": backend.mode(),
        "current": backend.current(),
        **_preset_info(),
    })
    return out


class ModelIn(BaseModel):
    backend: str
    model: str


@app.post("/model")
def model_set(body: ModelIn):
    try:
        backend.set_model(body.backend, body.model)
        backend.set_mode(body.backend)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    print(f"[llm] using {body.model} on {body.backend}", flush=True)
    return {"ok": True, "backend": body.backend, "model": body.model,
            "mode": backend.mode()}


class BackendIn(BaseModel):
    mode: str


@app.get("/backend")
def backend_get():
    return {
        "mode": backend.mode(),
        "current": backend.current(),
        "choices": list(backend.VALID),
    }


@app.post("/backend")
def backend_set(body: BackendIn):
    try:
        backend.set_mode(body.mode)
    except ValueError as e:
        return {"ok": False, "error": str(e), "mode": backend.mode()}
    print(f"[llm] backend switched to {backend.mode()}", flush=True)
    return {"ok": True, "mode": backend.mode(), "current": backend.current()}


def _preset_info():
    return {
        "preset": cfg.preset(),
        "presets": [{"name": n, "label": cfg.preset_label(n)} for n in cfg.presets()],
    }


@app.get("/preset")
def preset_get():
    return _preset_info()


class PresetIn(BaseModel):
    name: str


@app.post("/preset")
def preset_set(body: PresetIn):
    try:
        cfg.set_preset(body.name)
    except ValueError as e:
        return {"ok": False, "error": str(e), **_preset_info()}
    print(f"[config] personality switched to {cfg.preset_label(cfg.preset())}", flush=True)
    return {"ok": True, **_preset_info(), "idle": idle.status(),
            "barge_in": _barge_enabled()}


class MemoryIn(BaseModel):
    text: str


@app.get("/memory")
def memory_list():
    facts = sorted(memory.all_facts(), key=lambda f: f.get("updated", ""), reverse=True)
    return {"count": len(facts), "facts": facts, "ratings": ratings.counts()}


@app.get("/memory/view")
def memory_view():
    """The page behind "What she remembers…" in her menu."""
    from fastapi.responses import HTMLResponse
    from process.memory_page import HTML
    return HTMLResponse(HTML)


@app.post("/memory/{fact_id}/pin")
def memory_pin(fact_id: str):
    return {"ok": memory.pin(fact_id)}


class TestChatIn(BaseModel):
    messages: list[dict]


@app.post("/test/chat")
def test_chat(body: TestChatIn):
    """For docs/marina-bench/replay.py on this machine: her reply to a
    made-up conversation, with nothing kept."""
    reply = openai_api.rehearse(body.messages)
    if reply is None:
        return JSONResponse({"error": "The last message has to be from the user."},
                            status_code=400)
    return {"reply": reply}


class RateIn(BaseModel):
    good: bool
    note: str = ""


@app.post("/rate")
def rate_reply(body: RateIn):
    """Thumbs up or down on her last reply, saved with the exchange."""
    from process.llm_funcs.llm_scr import load_history
    entry = ratings.rate(body.good, load_history(), active_model(), body.note)
    if entry:
        print(f"[rated] {'good' if body.good else 'bad'}: {entry['her'][:80]}", flush=True)
    return {"ok": bool(entry), **ratings.counts()}


@app.post("/memory")
def memory_add(body: MemoryIn):
    fact = memory.add(body.text, source="manual")
    return {"ok": True, "added": fact, "duplicate": fact is None}


@app.delete("/memory/{fact_id}")
def memory_delete(fact_id: str):
    return {"ok": memory.remove(fact_id)}


@app.delete("/memory")
def memory_clear():
    memory.clear()
    return {"ok": True}


# Her memory and the personal conversation, served to the other bridges
# (see process.shared). Only reachable from the network with the token.

_LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}
# A proxy that serves her own app to other devices (the box's phone page)
# sends this, and gets what this machine gets.
WEB_TOKEN = str((config.get("web") or {}).get("token") or "").strip()


@app.middleware("http")
async def shared_guard(request, call_next):
    """From the network, only /shared/ (other bridges) and /v1/ (chat front
    ends), each with its own token. Everything else is for this machine."""
    if shared.SERVE_TOKEN or openai_api.enabled() or WEB_TOKEN:
        client = request.client.host if request.client else ""
        if client not in _LOCAL_CLIENTS:
            sent = request.headers.get("authorization", "").encode()
            path = request.url.path

            def has(token):
                return bool(token) and hmac.compare_digest(sent, f"Bearer {token}".encode())

            ok = (has(WEB_TOKEN)
                  or (path.startswith("/shared/") and has(shared.SERVE_TOKEN))
                  or (path.startswith("/v1/") and openai_api.enabled()
                      and has(openai_api.KEY)))
            if not ok:
                return JSONResponse({"error": "forbidden"}, status_code=403)
    return await call_next(request)


class SharedFactIn(BaseModel):
    text: str
    source: str = "auto"
    due: str | None = None


class SharedTurnIn(BaseModel):
    messages: list[dict]


@app.get("/shared/memory")
def shared_memory():
    return memory.local_facts()


@app.post("/shared/memory")
def shared_memory_add(body: SharedFactIn):
    fact = memory.local_add(body.text, source=body.source, due=body.due)
    if fact:
        print(f"[memory] +{fact['text']} (from another bridge)", flush=True)
    return {"fact": fact}


@app.post("/shared/memory/{fact_id}/pin")
def shared_memory_pin(fact_id: str):
    return {"ok": memory.local_pin(fact_id)}


class SharedStateIn(BaseModel):
    value: object = None


@app.get("/shared/state/{key}")
def shared_state(key: str):
    return {"value": her_state.local_get(key)}


@app.post("/shared/state/{key}")
def shared_state_put(key: str, body: SharedStateIn):
    her_state.local_put(key, body.value)
    return {"ok": True}


@app.delete("/shared/memory/{fact_id}")
def shared_memory_remove(fact_id: str):
    return {"ok": memory.local_remove(fact_id)}


@app.delete("/shared/memory")
def shared_memory_clear():
    memory.local_clear()
    return {"ok": True}


@app.get("/shared/history")
def shared_history():
    return load_local_history()


@app.post("/shared/history")
def shared_history_add(body: SharedTurnIn):
    msgs = [{"role": m["role"], "content": m["content"],
             **({"at": m["at"]} if isinstance(m.get("at"), str) else {})}
            for m in body.messages
            if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    if msgs:
        append_local(msgs)
    return {"ok": True, "added": len(msgs)}


@app.delete("/shared/history")
def shared_history_clear():
    reset_local_history()
    return {"ok": True}


@app.post("/call/start")
def call_start():
    """Start a call. Streams her picking up and saying hello; that greeting
    isn't saved as something you said. Replies use the call style until
    /call/end."""
    threading.Thread(target=whisper, daemon=True).start()
    call.start()
    idle.note_interaction()
    return StreamingResponse(
        _stream_reply(None, True, transcript="", extra_system=call.pick_up()),
        media_type="application/x-ndjson")


@app.post("/call/end")
def call_end():
    _drop_ear()
    if recorder.is_monitoring:
        recorder.cancel()
    return call.end()


@app.get("/call")
def call_status():
    return call.status()


@app.post("/reset")
def reset():
    reset_history()
    return {"ok": True}


class MuteIn(BaseModel):
    muted: bool


@app.get("/idle/status")
def idle_status():
    return idle.status()


@app.post("/idle/mute")
def idle_mute(body: MuteIn):
    value = idle.set_muted(body.muted)
    print(f"[idle] openers {'muted' if value else 'unmuted'}", flush=True)
    return {"ok": True, "muted": value}


def _reply_text(events):
    """Pass a reply's events through, keeping what she said for a push."""
    said = {"text": ""}

    def run():
        for line in events:
            try:
                ev = json.loads(line)
                if ev.get("type") in ("done", "interrupted"):
                    said["text"] = ev.get("reply") or ""
            except (ValueError, TypeError):
                pass
            yield line
    return run(), said


def _idle_stream(timeout, client="desk"):
    """Long poll: returns when she has something unprompted to say.

    A phone only gets her unprompted words while it says it is in front;
    from the background they go out as a push instead (see process.push),
    since a suspended app would never hear them."""
    phone = client == "phone"
    if phone:
        push.phone_polled()
    else:
        push.desk_stream(True)
    try:
        yield from _idle_wait(timeout, phone)
    finally:
        if not phone:
            push.desk_stream(False)


def _idle_wait(timeout, phone):
    waited = 0.0
    while waited < timeout:
        if phone and not push.phone_here():
            time.sleep(2.0)
            waited += 2.0
            yield _ndjson({"type": "waiting"})
            continue
        if call.active():
            # On a call she only answers; nothing unprompted cuts across it.
            time.sleep(2.0)
            waited += 2.0
            yield _ndjson({"type": "waiting"})
            continue
        announcement = tools.pending_announcement()
        if announcement:
            idle.note_interaction()
            print("[idle] a timer went off", flush=True)
            events, said = _reply_text(_stream_reply(None, True, transcript="",
                                                     extra_system="\n\n" + announcement))
            yield from events
            # Heard on a desktop, but they may not be at it: the phone gets it too.
            if not phone and not push.phone_here():
                push.send(said["text"], tags=["alarm_clock"])
            return

        noticed = notice.poll()
        if noticed and idle.may_notice():
            idle.note_spoken()
            print("[idle] bringing up something she noticed", flush=True)
            yield from _stream_reply(None, True, transcript="", extra_system=noticed)
            return

        if idle.due():
            idle.note_spoken()
            print("[idle] saying something unprompted", flush=True)
            yield from _stream_reply(None, True, transcript="",
                                     extra_system=idle.OPENER_INSTRUCTION)
            return
        time.sleep(2.0)
        waited += 2.0
        yield _ndjson({"type": "waiting"})
    yield _ndjson({"type": "idle"})


@app.get("/idle/listen")
def idle_listen(timeout: float = 120.0, client: str = "desk"):
    if not idle.enabled():
        return StreamingResponse(iter([_ndjson({"type": "disabled"})]),
                                 media_type="application/x-ndjson")
    return StreamingResponse(_idle_stream(timeout, client),
                             media_type="application/x-ndjson")


class RoomNoteIn(BaseModel):
    text: str
    topic: str = ""
    kind: str = "chat"
    others: list[str] = []


@app.get("/room/context")
def room_context():
    """For the Room of AIs connector: who she is and what she's done there
    before, so the room gets the same Marina (see process.room)."""
    from process import room
    return {"context": room.context()}


@app.post("/room/note")
def room_note(body: RoomNoteIn):
    """The connector, after she says or hands in something in the room."""
    from process import room
    entry = room.note(body.text, body.topic, body.kind, body.others)
    return {"ok": entry is not None}


class PresenceIn(BaseModel):
    front: bool


@app.post("/presence")
def presence(body: PresenceIn):
    """The phone app coming to the front or leaving it."""
    push.phone_presence(body.front)
    return {"ok": True, "push": push.enabled()}


def _say_unprompted(extra_system, tags=None):
    """Nobody has her app open: she says it anyway, it is saved like any
    other turn, and it goes to the phone as a push."""
    events, said = _reply_text(_stream_reply(None, False, transcript="",
                                             extra_system=extra_system))
    for _ in events:
        pass
    push.send(said["text"], tags=tags)


def _push_loop():
    """Her unprompted words when no app is there to hear them."""
    while True:
        time.sleep(3.0)
        try:
            if push.phone_here() or push.desk_here() or call.active():
                continue
            announcement = tools.pending_announcement()
            if announcement:
                idle.note_interaction()
                print("[push] a timer went off with no app open", flush=True)
                _say_unprompted("\n\n" + announcement, tags=["alarm_clock"])
                continue
            if push.OPENERS and idle.enabled() and idle.due():
                idle.note_spoken()
                print("[push] saying something unprompted with no app open", flush=True)
                _say_unprompted(idle.OPENER_INSTRUCTION)
        except Exception as e:
            print(f"[push] {type(e).__name__}: {e}", flush=True)
            time.sleep(30)


@app.get("/voices")
def voices():
    return {"voices": kokoro_voices()}


@app.post("/warmup")
def warmup():
    whisper()
    warmup_tts()
    return {"ok": True}


if openai_api.enabled():
    openai_api.mount(app)

_web = config.get("web") or {}
if _web.get("enabled"):
    # Last, because it mounts the avatar UI at / and would shadow later routes.
    from process import web
    web.mount(app, _web)


if __name__ == "__main__":
    import uvicorn

    from process import telegram
    telegram.start(transcribe=lambda path: transcribe_file(whisper(), path),
                   synthesize=synthesize)

    if push.enabled():
        threading.Thread(target=_push_loop, daemon=True, name="push").start()
        print(f"[push] notifications through ntfy ({push.URL})", flush=True)

    from process import satellite
    satellite.start(transcribe=lambda audio: transcribe_audio(whisper(), audio, prompt=WAKE_PROMPT),
                    synthesize=synthesize)

    bridge = config.get("bridge", {})
    uvicorn.run(
        app,
        host=bridge.get("host", "127.0.0.1"),
        port=int(bridge.get("port", 8765)),
        log_level="warning",
    )
