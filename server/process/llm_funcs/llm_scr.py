"""LLM conversation with on-disk history.

Speaks the OpenAI chat-completions API, which is the one dialect that OpenAI,
Ollama, llama.cpp, LM Studio and vLLM all implement. Set `llm.base_url` in
character_config.yaml to point at a local server instead of OpenAI.
"""
import json
import os
import random
import time

from openai import OpenAI

from process.backend import current as backend_current
from process.backend import mode as backend_mode
from process.backend import model_for
from process.backend import note_used
from process.config import load_config, resolve
from process.memory import extract as memory_extract
from process.memory import persona
from process.memory import store as memory

char_config = load_config()

# `llm:` is the current shape; the bare OPENAI_API_KEY / model keys are what
# upstream used, kept working so an upstream config still runs.
_llm = char_config.get("llm") or {}

BASE_URL = (_llm.get("base_url") or "").strip() or None
API_KEY = _llm.get("api_key") or char_config.get("OPENAI_API_KEY") or "not-needed"
MODEL = _llm.get("model") or char_config.get("model")
TEMPERATURE = _llm.get("temperature", 1.0)
MAX_TOKENS = _llm.get("max_tokens", 2048)

# How many past turns stay verbatim in the prompt. Everything older is gone
# from the transcript — anything worth keeping has been distilled into memory
# by then. Bounded history is what stops the context window growing forever.
HISTORY_TURNS = int(_llm.get("history_turns", 12))
REMEMBER = bool(_llm.get("remember", True))

HISTORY_FILE = resolve(char_config["history_file"])
BASE_SYSTEM_PROMPT = char_config["presets"]["default"]["system_prompt"]


def system_message():
    """The system prompt plus whatever she currently remembers."""
    return {
        "role": "system",
        "content": BASE_SYSTEM_PROMPT
        + persona.as_prompt_block()
        + memory.as_prompt_block(),
    }

# Failover: the GPU box is only reachable on the home network. Off it, she
# falls back to a model on this Mac rather than simply failing.
FALLBACK_BASE = (_llm.get("fallback_base_url") or "").strip() or None
FALLBACK_MODEL = _llm.get("fallback_model") or MODEL
FALLBACK_KEY = _llm.get("fallback_api_key") or "not-needed"
STICKY = float(_llm.get("fallback_sticky_seconds", 30))

# Qwen3 and friends are hybrid reasoning models: left alone they emit a long
# <think> block, which llama.cpp returns as reasoning_content — so a short
# request can burn its whole token budget and hand back empty content. She
# talks in one or two sentences and speaks them aloud, so thinking is pure
# latency here. Sent per-request rather than set on the server, which is
# shared with other people who may well want it on.
THINKING = bool(_llm.get("thinking", False))

# llama-server keeps a fixed seed when a request does not carry one, so the
# same question gets a byte-identical answer every time — she repeated herself
# verbatim with the previous exchange sitting in her own context. Set an
# integer here to make runs reproducible; leave it null for a live-feeling
# companion.
SEED = _llm.get("seed")

client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=20.0, max_retries=0)
fallback_client = (
    OpenAI(api_key=FALLBACK_KEY, base_url=FALLBACK_BASE, timeout=60.0, max_retries=0)
    if FALLBACK_BASE else None
)

# When the primary fails, stop hammering it for a while — otherwise every turn
# pays the connection timeout before falling back.
_primary_down_until = 0.0
_active = "server"


def describe_endpoint():
    """The base URL actually being used, for /health."""
    if backend_current() == "local" and FALLBACK_BASE:
        return FALLBACK_BASE
    return BASE_URL or "https://api.openai.com/v1"


def active_model():
    """The model name of whichever backend is currently in use."""
    return model_for()


def active_endpoint():
    """Which backend is currently in use, for /health."""
    return backend_current()


def _pick():
    """Honour the selected mode; 'auto' also respects the failover cooldown."""
    m = backend_mode()
    if m == "local":
        if not fallback_client:
            raise RuntimeError("Local mode selected but no fallback_base_url configured.")
        return fallback_client, model_for("local"), "local"
    if m == "server":
        return client, model_for("server"), "server"
    # auto
    if fallback_client and time.time() < _primary_down_until:
        return fallback_client, model_for("local"), "local"
    return client, model_for("server"), "server"


def _request_extras(kw):
    """Per-request options the shared server should not be forced to set.

    Other people use the same llama-server, so anything opinionated belongs on
    the request rather than the daemon. Unknown keys are ignored by servers
    that do not use a chat template, so this is safe for Ollama too.
    """
    kw = dict(kw)
    if not THINKING:
        extra = dict(kw.get("extra_body") or {})
        tmpl = dict(extra.get("chat_template_kwargs") or {})
        tmpl.setdefault("enable_thinking", False)
        extra["chat_template_kwargs"] = tmpl
        kw["extra_body"] = extra
    if "seed" not in kw:
        kw["seed"] = SEED if SEED is not None else random.randrange(2**31)
    return kw


def chat_completion(messages, **kw):
    """Call the selected backend.

    In 'auto' this falls back to the Mac when the server is unreachable. In
    'server' it does not — a failure is reported, so you always know where
    your words went.
    """
    global _primary_down_until, _active
    from openai import APIConnectionError, APITimeoutError

    c, model, which = _pick()
    kw = _request_extras(kw)
    try:
        out = c.chat.completions.create(model=model, messages=messages, **kw)
        if which == "server" and _active != "server":
            print("[llm] server is back", flush=True)
        _active = which
        note_used(which)
        return out
    except (APIConnectionError, APITimeoutError):
        if which != "server" or backend_mode() != "auto" or not fallback_client:
            raise
        _primary_down_until = time.time() + STICKY
        _active = "local"
        note_used("local")
        print(f"[llm] server unreachable — using {FALLBACK_MODEL} on this Mac",
              flush=True)
        return fallback_client.chat.completions.create(
            model=model_for("local"), messages=messages, **kw)


def _flatten(message):
    """Accept both plain strings and the Responses-API list-of-parts shape.

    Upstream stored history as [{"type": "input_text", "text": ...}]. Older
    history files therefore need converting rather than crashing the client.
    """
    content = message.get("content")
    if isinstance(content, str):
        return {"role": message["role"], "content": content}

    if isinstance(content, list):
        text = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        )
        return {"role": message["role"], "content": text}

    return {"role": message["role"], "content": str(content)}


def load_history():
    """History lives on this Mac only, and is shared across backends —
    switching brains does not give you a different conversation."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                raw = json.load(f)
            except json.JSONDecodeError:
                # Corrupt file: start the transcript over. The system prompt is
                # added separately each turn, and memory is a different file.
                return []
        history = [_flatten(m) for m in raw if isinstance(m, dict) and "role" in m]
        # Drop any stored system message; it is rebuilt fresh each turn so that
        # config edits and new memories both take effect immediately.
        return [m for m in history if m["role"] != "system"]
    return []


def save_history(history):
    # Only the recent window is persisted, so the file cannot grow without end.
    trimmed = [m for m in history if m["role"] != "system"][-(HISTORY_TURNS * 2):]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(trimmed, f, indent=2)


def reset_history():
    """Forget the conversation and start over from the system prompt."""
    if os.path.exists(HISTORY_FILE):
        os.remove(HISTORY_FILE)


def get_reply(messages):
    return chat_completion(
        messages,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        stream=False,
    )


def note_exchange(user_text, assistant_text):
    """Record a turn that didn't come from the chat model (e.g. a screen look),
    so she can refer back to it."""
    history = load_history()[-(HISTORY_TURNS * 2):]
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": assistant_text})
    save_history(history)


def llm_response(user_input):
    history = load_history()[-(HISTORY_TURNS * 2):]
    history.append({"role": "user", "content": user_input})

    # System prompt is rebuilt every turn so new memories land immediately.
    completion = get_reply([system_message()] + history)
    reply = (completion.choices[0].message.content or "").strip()

    history.append({"role": "assistant", "content": reply})
    save_history(history)

    if REMEMBER:
        # Runs on a background thread — the reply is already on its way.
        memory_extract.remember_async(client, MODEL, user_input, reply)

    return reply
