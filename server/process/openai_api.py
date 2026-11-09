"""An OpenAI-style API, so chat front ends like Open WebUI can talk to her.

Two models:

  marina        her, with her personality, the memory she shares with every
                other way of talking to her, and her tools. Each chat in the
                front end is its own thread, separate from the personal
                conversation, but what she learns about you in one is kept.
  marina-voice  her, for a speaker in another room (see satellite): told
                she is talking out loud, and answers with only what is said,
                no *actions*. The speaker's own instructions are dropped,
                since they describe its tools, not hers.
  marina-plain  the same model with none of that, for the front end's own
                housekeeping, like naming chats.

Turned on by `api.key`. From the network the bridge then answers /v1/ to
requests that carry it (see the guard in marina_server).
"""
import json
import re
import time
import uuid

from fastapi import Body
from fastapi.responses import JSONResponse, StreamingResponse

from process.config import load_config
from process.llm_funcs import llm_scr
from process.memory import extract as memory_extract
from process.text_func.speech import split_reply

KEY = str((load_config().get("api") or {}).get("key") or "").strip()

WINDOW = 40

CHAT_WINDOW = """

Right now you are in a chat window on their screen, not speaking and not
texting on a phone. It renders markdown, so here code blocks, lists and
headings are fine when they help, and longer answers are fine when the
task needs them. You are still you: same voice, same opinions. No *actions*
in asterisks."""

SPEAKER = """

Right now you are talking out loud through a speaker in their room, not
texting and not in a chat window. They hear you; they can't see anything.
Keep it short, the way you'd answer someone across the room: no lists, no
markdown, no links, no code, and no *actions* in asterisks."""


def enabled():
    return bool(KEY)


# Her steps, shown in the chat as she works. Removed again from what she
# reads back, so she doesn't start writing them herself.
_STEP = "> \u2699\ufe0f "
_STEP_LINES = re.compile(r"^> \u2699\ufe0f .*\n*", re.M)


def _step(activity):
    where = "on her machine" if activity.where == "vm" else "on your Mac"
    return f"{_STEP}*{where}:* {activity.label}\n\n"


def _unstep(content):
    return _STEP_LINES.sub("", content).strip() if isinstance(content, str) else content


def _text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return ""


def _chunk(cid, model, delta, finish=None):
    return "data: " + json.dumps({
        "id": cid, "object": "chat.completion.chunk", "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
    }, ensure_ascii=False) + "\n\n"


def _completion(cid, model, text):
    return {
        "id": cid, "object": "chat.completion", "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": text}}],
    }


def _her(body, voice=False):
    messages = [m for m in body.get("messages") or [] if isinstance(m, dict)]
    their_system = "\n\n".join(_text(m.get("content")) for m in messages
                               if m.get("role") == "system").strip()
    chat = [{"role": m["role"],
             "content": _unstep(m.get("content") or "") if m["role"] == "assistant"
             else m.get("content") or ""}
            for m in messages if m.get("role") in ("user", "assistant")]
    if not chat or chat[-1]["role"] != "user":
        return None, None, None
    *before, last = chat
    if voice:
        extra = SPEAKER
    else:
        extra = CHAT_WINDOW + (f"\n\nThey added this for the chat:\n{their_system}"
                               if their_system else "")
    stream = llm_scr.llm_stream(last["content"], extra_system=extra,
                                history=before[-WINDOW:])
    return stream, _text(last["content"]), before


def _remember(user_text, reply):
    if llm_scr._remember() and user_text:
        memory_extract.remember_async(*llm_scr._extract_backend(), user_text, reply)


def mount(app):
    @app.get("/v1/models")
    def models():
        now = int(time.time())
        return {"object": "list", "data": [
            {"id": "marina", "object": "model", "created": now, "owned_by": "marina"},
            {"id": "marina-voice", "object": "model", "created": now, "owned_by": "marina"},
            {"id": "marina-plain", "object": "model", "created": now, "owned_by": "marina"},
        ]}

    # Not async: her reply loop blocks, so this runs on the thread pool.
    @app.post("/v1/chat/completions")
    def chat(body: dict = Body(...)):
        model = body.get("model") or "marina"
        streaming = bool(body.get("stream"))
        cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"

        if model == "marina-plain":
            kw = {k: body[k] for k in ("temperature", "max_tokens", "top_p") if k in body}
            if streaming:
                def plain():
                    for ev in llm_scr.chat_completion(body.get("messages") or [],
                                                      stream=True, **kw):
                        yield "data: " + ev.model_dump_json(exclude_none=True) + "\n\n"
                    yield "data: [DONE]\n\n"
                return StreamingResponse(plain(), media_type="text/event-stream")
            out = llm_scr.chat_completion(body.get("messages") or [], **kw)
            return JSONResponse(out.model_dump(exclude_none=True))

        voice = model == "marina-voice"
        stream, user_text, _before = _her(body, voice)
        if stream is None:
            return JSONResponse({"error": {"message": "The last message has to be from the user."}},
                                status_code=400)
        print(f"[{'speaker' if voice else 'chat ui'}] you: {user_text[:120]}", flush=True)

        if voice:
            # Always whole: what she says goes to text to speech in one go.
            reply = "".join(stream).strip()
            _remember(user_text, reply)
            spoken = split_reply(reply)["speech"].strip()
            print(f"[speaker] marina: {spoken[:120]}", flush=True)
            return JSONResponse(_completion(cid, "marina-voice", spoken))

        if not streaming:
            reply = "".join(stream).strip()
            _remember(user_text, reply)
            return JSONResponse(_completion(cid, "marina", reply))

        def events():
            said = []
            yield _chunk(cid, "marina", {"role": "assistant", "content": ""})
            try:
                for piece in stream:
                    if isinstance(piece, llm_scr.Activity) and piece.label:
                        yield _chunk(cid, "marina", {"content": _step(piece)})
                        continue
                    if not piece:
                        # Between tool calls. An SSE comment keeps the
                        # connection honest, so a closed tab stops her.
                        yield ": working\n\n"
                        continue
                    said.append(piece)
                    yield _chunk(cid, "marina", {"content": piece})
            except Exception as e:
                yield _chunk(cid, "marina", {"content": f"\n\n(my brain didn't answer: {type(e).__name__})"})
            yield _chunk(cid, "marina", {}, "stop")
            yield "data: [DONE]\n\n"
            reply = "".join(said).strip()
            print(f"[chat ui] marina: {reply[:120]}", flush=True)
            # (said holds only her words; the steps went straight out.)
            _remember(user_text, reply)

        return StreamingResponse(events(), media_type="text/event-stream")
