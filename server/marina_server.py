"""Local bridge between the Marina desktop app and the ASR / LLM / TTS pipeline.

Run this from the repo root:

    python -m uvicorn server.marina_server:app --host 127.0.0.1 --port 8765

or just:

    python server/marina_server.py

Nothing here listens on a public interface. The heavy voice model
(GPT-SoVITS) lives on your server and is reached over HTTP.
"""
import base64
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "server"))

from fastapi import FastAPI, File, UploadFile  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from process.asr_func.asr_push_to_talk import build_model, transcribe_file  # noqa: E402
from process.asr_func.recorder import Recorder  # noqa: E402
from process.config import load_config  # noqa: E402
from process.llm_funcs.llm_scr import (  # noqa: E402
    active_endpoint,
    active_model,
    describe_endpoint,
    llm_response,
    note_exchange,
    reset_history,
)
from process.tts_func.engine import (  # noqa: E402
    TTSError,
    describe as describe_tts,
    kokoro_voices,
    synthesize,
)
from process.tts_func.engine import warmup as warmup_tts  # noqa: E402
from process.text_func.speech import split_reply  # noqa: E402
from process import backend  # noqa: E402
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
        # A bad API key / rate limit / dropped network must not look like the
        # bridge itself being down, so report it as a readable message.
        msg = getattr(getattr(e, "response", None), "text", "") or str(e)
        if "invalid_api_key" in msg or "Incorrect API key" in msg:
            msg = "OpenAI rejected the API key. Set OPENAI_API_KEY in character_config.yaml."
        elif "rate_limit" in msg or "429" in msg:
            msg = "OpenAI rate-limited the request. Wait a moment and try again."
        else:
            msg = f"LLM call failed: {type(e).__name__}: {str(e)[:200]}"
        out["error"] = msg
        print(f"[llm] {msg}", flush=True)
        return out

    # Actions like *tilts head* become animations; everything else is spoken.
    parts = split_reply(reply)
    out["reply"] = parts["display"]
    out["speech"] = parts["speech"]
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
    }


@app.post("/chat")
def chat(body: ChatIn):
    """Typed input."""
    text = body.text.strip()
    if not text:
        return {"transcript": "", "reply": "", "speech": "", "cues": [],
                "audio": None, "error": "Empty message."}
    print(f"[you] {text}", flush=True)
    result = _respond(text, body.speak)
    print(f"[marina] {result['reply']}", flush=True)
    return result


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


@app.post("/listen/cancel")
def listen_cancel():
    recorder.cancel()
    return {"ok": True}


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
