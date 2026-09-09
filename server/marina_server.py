"""Local bridge between the Marina desktop app and the ASR / LLM / TTS pipeline.

Run this from the repo root:

    python -m uvicorn server.marina_server:app --host 127.0.0.1 --port 8765

or just:

    python server/marina_server.py

Nothing here listens on a public interface. The heavy voice model
(GPT-SoVITS) lives on your server and is reached over HTTP.
"""
import base64
import json
import sys
import tempfile
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "server"))

from fastapi import FastAPI, File, UploadFile  # noqa: E402
from fastapi.responses import StreamingResponse  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from process.asr_func.asr_push_to_talk import build_model, transcribe_file  # noqa: E402
from process.asr_func.recorder import Recorder  # noqa: E402
from process.asr_func.vad import VAD  # noqa: E402
from process.config import load_config  # noqa: E402
from process.llm_funcs.llm_scr import (  # noqa: E402
    active_endpoint,
    active_model,
    describe_endpoint,
    llm_response,
    llm_stream,
    note_exchange,
    reset_history,
    save_turn,
)
from process.tts_func.engine import (  # noqa: E402
    TTSError,
    describe as describe_tts,
    kokoro_voices,
    synthesize,
)
from process.tts_func.engine import warmup as warmup_tts  # noqa: E402
from process.text_func.speech import SentenceSplitter, split_reply  # noqa: E402
from process import backend  # noqa: E402
from process import idle  # noqa: E402
from process.tools import registry as tools  # noqa: E402
from process.memory import store as memory  # noqa: E402
from process.vision.look import (  # noqa: E402
    ENABLED as VISION_ENABLED,
    MODEL as VISION_MODEL,
    VisionError,
    describe as describe_screen,
)

config = load_config()

app = FastAPI(title="Marina bridge")

# The renderer runs from file:// so its Origin is "null".
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_whisper = None
recorder = Recorder()


def whisper():
    """Load Whisper lazily so the server starts instantly and text-only
    chat never pays for the model at all."""
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
    """A readable reason, so a bad key never looks like the bridge being down."""
    msg = getattr(getattr(e, "response", None), "text", "") or str(e)
    if "invalid_api_key" in msg or "Incorrect API key" in msg:
        return "OpenAI rejected the API key. Set OPENAI_API_KEY in character_config.yaml."
    if "rate_limit" in msg or "429" in msg:
        return "OpenAI rate-limited the request. Wait a moment and try again."
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

    # Actions like *tilts head* become animations; everything else is spoken.
    parts = split_reply(reply)
    out["reply"] = parts["display"]
    out["speech"] = parts["speech"]
    # Which brain actually answered. /health reports intent; a failover happens
    # mid-request, and without this the UI keeps claiming the GPU box while she
    # is quietly running on the 3B here.
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
        # Still show the text — a dead TTS box shouldn't kill the conversation.
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
        "tts": describe_tts(),
        "whisper_loaded": _whisper is not None,
        "recording": recorder.is_recording,
        "memories": len(memory.all_facts()),
        "vision": VISION_MODEL if VISION_ENABLED else None,
        "barge_in": BARGE_ENABLED,
        "idle": idle.status(),
    }


@app.post("/chat")
def chat(body: ChatIn):
    """Typed input."""
    text = body.text.strip()
    if not text:
        return {"transcript": "", "reply": "", "speech": "", "cues": [],
                "audio": None, "error": "Empty message."}
    print(f"[you] {text}", flush=True)
    idle.note_interaction()
    result = _respond(text, body.speak)
    print(f"[marina] {result['reply']}", flush=True)
    return result


# The reply currently being generated. Interrupting her is a message to this
# stream, not an edit applied to the transcript afterwards: the generator stops
# pulling from the model and writes only the segments that were actually heard.
# Editing history after the fact meant two writers racing for the same file,
# and the loser's turn came back as a truncated stranger's.
_stream = {"id": 0, "stop_at": None}
_stream_lock = threading.Lock()


def _ndjson(event):
    return json.dumps(event, ensure_ascii=False) + "\n"


def _speak_segment(segment, index, speak):
    """One segment of a streamed reply, ready to play."""
    parts = split_reply(segment)
    event = {
        "type": "chunk",
        "index": index,
        "reply": parts["display"],
        "speech": parts["speech"],
        "cues": parts["cues"],
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
            # A dead voice must not kill the conversation — the words still go
            # to the bubble, and the next segment gets its own attempt.
            event["error"] = str(e)
            print(f"[tts] {e}", flush=True)
    return event


def _stream_reply(user_text, speak=True, transcript=None, extra_system=None,
                  record=True):
    """Generate, segment, synthesize and emit, one sentence at a time.

    The whole point is the first sentence: the model is still writing and
    Kokoro runs at 3-4x realtime once warm, so once the opening segment is
    playing, synthesis stays ahead of playback for the rest of the reply.
    """
    with _stream_lock:
        _stream["id"] += 1
        _stream["stop_at"] = None
        stream_id = _stream["id"]

    def stop_after():
        """How many segments were heard, or None to carry on.

        Superseded is not the same as interrupted. A newer reply taking over
        should stop this one generating, but everything it already emitted was
        spoken out loud — recording zero of it would delete a turn the user
        actually heard.
        """
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
    generator = llm_stream(user_text, extra_system=extra_system)

    def emit(segment):
        """None for a segment with nothing in it to say or perform."""
        nonlocal index
        event = _speak_segment(segment, index, speak)
        if not event["speech"] and not event["cues"]:
            # Models end on a stray dash or an ellipsis of its own, and a
            # chunk carrying only punctuation puts a blank line in the bubble
            # and a click in the audio queue.
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
        # Only what left the speakers goes into the transcript. The dash reads
        # as being cut off, so on the next turn she is more likely to
        # acknowledge the interruption than to carry on as if it never
        # happened.
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
    """Typed input, answered a sentence at a time.

    Same conversation as /chat — the non-streaming endpoint stays for the
    terminal client and for anything that would rather have one JSON object.
    """
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


@app.post("/interrupt")
def interrupt(body: InterruptIn):
    """Stop her mid-reply, having heard `chunks` sentences of it.

    The model runs well ahead of the speakers, so an interruption has to reach
    the generator rather than the transcript: the stream stops pulling tokens
    and records only the sentences that were actually heard. Otherwise she
    answers follow-ups about points she never got to make.
    """
    with _stream_lock:
        _stream["stop_at"] = max(0, body.chunks)
        stream_id = _stream["id"]
    return {"ok": True, "id": stream_id, "heard": max(0, body.chunks)}


@app.post("/voice")
def voice(audio: UploadFile = File(...), speak: bool = True):
    """Spoken input: a recording from the app's microphone."""
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
    """Begin capturing the microphone. Whisper is warmed up in the
    background so the model load overlaps with you talking."""
    import threading

    threading.Thread(target=whisper, daemon=True).start()
    # Barge-in may be holding the microphone. Pressing the button is an
    # explicit request for it, so take it back rather than reporting busy.
    if recorder.is_monitoring:
        recorder.cancel()
    started = recorder.start()
    return {"ok": True, "started": started, "already_recording": not started}


@app.post("/listen/stop")
def listen_stop(speak: bool = True):
    """Stop capturing, transcribe, answer, and synthesize."""
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


@app.post("/listen/stop/stream")
def listen_stop_stream():
    """Stop capturing, transcribe, and stream the answer.

    Voice is the main way in, so it gets the same sentence-at-a-time treatment
    as typing — transcription is already a second of waiting, and following it
    with the whole reply before she opens her mouth is the long version of
    exactly what streaming is here to fix.
    """
    def fail(message):
        return StreamingResponse(
            iter([_ndjson({"type": "error", "message": message})]),
            media_type="application/x-ndjson")

    path = recorder.stop()
    if path is None:
        return fail("Nothing recorded.")

    try:
        transcript = transcribe_file(whisper(), path)
    finally:
        path.unlink(missing_ok=True)

    if not transcript:
        return fail("Didn't catch that.")

    print(f"[you] {transcript}", flush=True)
    idle.note_interaction()
    return StreamingResponse(
        _stream_reply(transcript, True, transcript=transcript),
        media_type="application/x-ndjson")


@app.post("/listen/cancel")
def listen_cancel():
    recorder.cancel()
    return {"ok": True}


# ----------------------------------------------------------------------
#  Barge-in
# ----------------------------------------------------------------------

_barge = config.get("barge_in") or {}
BARGE_ENABLED = bool(_barge.get("enabled", True))


def _make_vad():
    from process.asr_func.recorder import SAMPLERATE

    return VAD(
        SAMPLERATE,
        margin_db=float(_barge.get("margin_db", 12.0)),
        speech_ms=int(_barge.get("speech_ms", 220)),
        silence_ms=int(_barge.get("silence_ms", 800)),
    )


def _barge_stream(timeout):
    """Listen while she talks, and turn talking over her into the next turn.

    One stream does the whole thing. The client opens it when she starts
    speaking; if nothing happens it closes quietly when she finishes. If you
    do cut in, the same stream carries the speech event, then the transcript,
    then her next reply — so from the client's side an interruption is just
    the conversation continuing.
    """
    import queue as _queue

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
                # The push-to-talk button took the microphone back.
                return
            try:
                event = recorder.events.get(timeout=0.25)
            except _queue.Empty:
                # Keeps the connection warm and, more usefully, gives the
                # client's read a chance to fail promptly when it hangs up.
                yield _ndjson({"type": "waiting"})
                continue

            if event == "start" and not heard:
                heard = True
                yield _ndjson({"type": "speech"})
                # From here it is an utterance, not a monitor: no timeout, we
                # wait for them to finish.
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
        # Whether they interrupted, timed out, or closed the window, the
        # microphone must not stay open.
        if recorder.is_monitoring:
            recorder.cancel()


@app.get("/barge/listen")
def barge_listen(timeout: float = 45.0):
    """Arm the microphone for the duration of a reply.

    Disabled by config, or with no `barge_in` section, this returns a single
    event and closes, so the client needs no special case.
    """
    if not BARGE_ENABLED:
        return StreamingResponse(
            iter([_ndjson({"type": "disabled"})]),
            media_type="application/x-ndjson")
    threading.Thread(target=whisper, daemon=True).start()
    return StreamingResponse(_barge_stream(timeout),
                             media_type="application/x-ndjson")


class SeeIn(BaseModel):
    image: str                    # base64, no data: prefix
    mime: str = "image/jpeg"
    question: str = ""
    speak: bool = True


@app.post("/see")
def see(body: SeeIn):
    """Look at a screenshot and answer a question about it.

    Only ever called when you explicitly ask her to look — the app never
    captures the screen on its own.
    """
    import base64 as _b64

    out = {"transcript": body.question or "(looked at the screen)",
           "reply": "", "speech": "", "cues": [], "audio": None, "error": None}

    try:
        raw = _b64.b64decode(body.image)
    except Exception:
        out["error"] = "Screenshot was not valid base64."
        return out

    print(f"[see] {len(raw)/1024:.0f} KB screenshot", flush=True)

    try:
        answer = describe_screen(raw, body.question, body.mime)
    except VisionError as e:
        out["error"] = str(e)
        print(f"[see] {e}", flush=True)
        return out

    parts = split_reply(answer)
    out["reply"] = parts["display"]
    out["speech"] = parts["speech"]
    # Which brain actually answered. /health reports intent; a failover happens
    # mid-request, and without this the UI keeps claiming the GPU box while she
    # is quietly running on the 3B here.
    out["backend"] = active_endpoint()
    out["model"] = active_model()
    out["cues"] = parts["cues"]
    print(f"[marina] {parts['speech']}", flush=True)

    # Record it as a normal exchange so she can refer back to what she saw.
    note_exchange(body.question or "What is on my screen?",
                  f"(looked at your screen) {answer}")

    if body.speak and out["speech"]:
        try:
            wav, visemes = synthesize(out["speech"])
            out["audio"] = _b64.b64encode(wav).decode("ascii")
            out["visemes"] = visemes
        except TTSError as e:
            out["error"] = str(e)

    return out


def _list_models(base_url, api_key):
    """Ask an OpenAI-compatible endpoint what it can serve."""
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
    """Everything selectable, grouped by backend. Unreachable backends come
    back empty rather than erroring, so the picker still renders."""
    from process.llm_funcs.llm_scr import (
        API_KEY, BASE_URL, FALLBACK_BASE, FALLBACK_KEY,
    )
    return {
        "server": _list_models(BASE_URL, API_KEY),
        "local": _list_models(FALLBACK_BASE, FALLBACK_KEY),
        "selected": backend.models(),
        "mode": backend.mode(),
        "current": backend.current(),
    }


class ModelIn(BaseModel):
    backend: str
    model: str


@app.post("/model")
def model_set(body: ModelIn):
    """Pick a model, and switch to that backend at the same time."""
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
    """Switch brains. History and memory stay on this Mac either way."""
    try:
        backend.set_mode(body.mode)
    except ValueError as e:
        return {"ok": False, "error": str(e), "mode": backend.mode()}
    print(f"[llm] backend switched to {backend.mode()}", flush=True)
    return {"ok": True, "mode": backend.mode(), "current": backend.current()}


class MemoryIn(BaseModel):
    text: str


@app.get("/memory")
def memory_list():
    """Everything she remembers, newest first."""
    facts = sorted(memory.all_facts(), key=lambda f: f.get("updated", ""), reverse=True)
    return {"count": len(facts), "facts": facts}


@app.post("/memory")
def memory_add(body: MemoryIn):
    """Teach her something directly, rather than waiting for her to notice it."""
    fact = memory.add(body.text, source="manual")
    return {"ok": True, "added": fact, "duplicate": fact is None}


@app.delete("/memory/{fact_id}")
def memory_delete(fact_id: str):
    return {"ok": memory.remove(fact_id)}


@app.delete("/memory")
def memory_clear():
    """Wipe long-term memory. Separate from /reset, which only clears the chat."""
    memory.clear()
    return {"ok": True}


@app.post("/reset")
def reset():
    """Forget the current conversation. Long-term memory is untouched —
    use DELETE /memory for that."""
    reset_history()
    return {"ok": True}


# ----------------------------------------------------------------------
#  Speaking first
# ----------------------------------------------------------------------

class MuteIn(BaseModel):
    muted: bool


@app.get("/idle/status")
def idle_status():
    return idle.status()


@app.post("/idle/mute")
def idle_mute(body: MuteIn):
    """One switch. Off means off — no openers until it is turned back on."""
    value = idle.set_muted(body.muted)
    print(f"[idle] openers {'muted' if value else 'unmuted'}", flush=True)
    return {"ok": True, "muted": value}


def _idle_stream(timeout):
    """Hold the line until she has something unprompted to say.

    A long poll rather than a push: the client keeps one of these open and
    reopens it when it returns, which needs no second channel and recovers
    from a dropped bridge on its own.
    """
    waited = 0.0
    while waited < timeout:
        # A timer they set themselves is not an unprompted thought, so it
        # ignores the quiet hours and the hourly cap. Being asked to say
        # something at a particular time and then not saying it is the one
        # failure this feature cannot have.
        announcement = tools.pending_announcement()
        if announcement:
            idle.note_interaction()
            print("[idle] a timer went off", flush=True)
            yield from _stream_reply(None, True, transcript="",
                                     extra_system="\n\n" + announcement)
            return

        if idle.due():
            idle.note_spoken()
            print("[idle] saying something unprompted", flush=True)
            yield from _stream_reply(None, True, transcript="",
                                     extra_system=idle.OPENER_INSTRUCTION)
            return
        time.sleep(2.0)
        waited += 2.0
        # Keeps the socket honest, and lets the client notice a dead bridge.
        yield _ndjson({"type": "waiting"})
    yield _ndjson({"type": "idle"})


@app.get("/idle/listen")
def idle_listen(timeout: float = 120.0):
    if not idle.ENABLED:
        return StreamingResponse(iter([_ndjson({"type": "disabled"})]),
                                 media_type="application/x-ndjson")
    return StreamingResponse(_idle_stream(timeout),
                             media_type="application/x-ndjson")


@app.get("/voices")
def voices():
    """Available Kokoro voicepacks (empty when using GPT-SoVITS)."""
    return {"voices": kokoro_voices()}


@app.post("/warmup")
def warmup():
    """Preload Whisper and the local voice while you decide what to say."""
    whisper()
    warmup_tts()
    return {"ok": True}


if __name__ == "__main__":
    import uvicorn

    bridge = config.get("bridge", {})
    uvicorn.run(
        app,
        host=bridge.get("host", "127.0.0.1"),
        port=int(bridge.get("port", 8765)),
        log_level="warning",
    )
