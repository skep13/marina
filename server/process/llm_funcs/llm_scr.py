"""Chat completions client with on-disk history.

Works with anything OpenAI-compatible (OpenAI, Ollama, llama.cpp, LM Studio,
vLLM). Set `llm.base_url` in character_config.yaml.
"""
import json
import os
import random
import threading
import time

from openai import OpenAI

from process.backend import current as backend_current
from process.backend import mode as backend_mode
from process.backend import model_for
from process.backend import note_used
from process.config import load_config, resolve_data
from process.memory import extract as memory_extract
from process.memory import persona
from process.memory import store as memory
from process.tools import context as ambient
from process.tools import registry as tools

char_config = load_config()

_llm = char_config.get("llm") or {}

BASE_URL = (_llm.get("base_url") or "").strip() or None
API_KEY = _llm.get("api_key") or char_config.get("OPENAI_API_KEY") or "not-needed"
MODEL = _llm.get("model") or char_config.get("model")
TEMPERATURE = _llm.get("temperature", 1.0)
MAX_TOKENS = _llm.get("max_tokens", 2048)

HISTORY_TURNS = int(_llm.get("history_turns", 12))
REMEMBER = bool(_llm.get("remember", True))

HISTORY_FILE = resolve_data(char_config["history_file"])
BASE_SYSTEM_PROMPT = char_config["presets"]["default"]["system_prompt"]


def _stable_context():
    from datetime import datetime
    now = datetime.now()
    h = now.hour
    part = ("the middle of the night" if h < 5 else "early morning" if h < 8 else
            "morning" if h < 12 else "afternoon" if h < 17 else
            "evening" if h < 22 else "late evening")
    return f"\n\nIt is {now:%A} {part}. Use this only if it is actually relevant."


def system_message():
    return {
        "role": "system",
        "content": BASE_SYSTEM_PROMPT + memory.as_prompt_block() + _stable_context(),
    }


FALLBACK_BASE = (_llm.get("fallback_base_url") or "").strip() or None
FALLBACK_MODEL = _llm.get("fallback_model") or MODEL
FALLBACK_KEY = _llm.get("fallback_api_key") or "not-needed"
STICKY = float(_llm.get("fallback_sticky_seconds", 30))

THINKING = bool(_llm.get("thinking", False))

SEED = _llm.get("seed")

REPEAT_PENALTY = float(_llm.get("repeat_penalty", 1.12))
FREQUENCY_PENALTY = float(_llm.get("frequency_penalty", 0.35))

TIMEOUT = float(_llm.get("timeout_seconds", 30.0))

client = OpenAI(api_key=API_KEY, base_url=BASE_URL, timeout=TIMEOUT, max_retries=0)
fallback_client = (
    OpenAI(api_key=FALLBACK_KEY, base_url=FALLBACK_BASE, timeout=60.0, max_retries=0)
    if FALLBACK_BASE else None
)

_primary_down_until = 0.0
_active = "server"


def describe_endpoint():
    if backend_current() == "local" and FALLBACK_BASE:
        return FALLBACK_BASE
    return BASE_URL or "https://api.openai.com/v1"


def active_model():
    return model_for()


def active_endpoint():
    return backend_current()


def _pick():
    m = backend_mode()
    if m == "local":
        if not fallback_client:
            raise RuntimeError("Local mode selected but no fallback_base_url configured.")
        return fallback_client, model_for("local"), "local"
    if m == "server":
        return client, model_for("server"), "server"
    if fallback_client and time.time() < _primary_down_until:
        return fallback_client, model_for("local"), "local"
    return client, model_for("server"), "server"


def _request_extras(kw):
    kw = dict(kw)
    if not THINKING:
        extra = dict(kw.get("extra_body") or {})
        tmpl = dict(extra.get("chat_template_kwargs") or {})
        tmpl.setdefault("enable_thinking", False)
        extra["chat_template_kwargs"] = tmpl
        kw["extra_body"] = extra
    if "seed" not in kw:
        kw["seed"] = SEED if SEED is not None else random.randrange(2**31)
    if FREQUENCY_PENALTY and "frequency_penalty" not in kw:
        kw["frequency_penalty"] = FREQUENCY_PENALTY
    if REPEAT_PENALTY and REPEAT_PENALTY != 1.0:
        extra = dict(kw.get("extra_body") or {})
        extra.setdefault("repeat_penalty", REPEAT_PENALTY)
        kw["extra_body"] = extra
    return kw


def chat_completion(messages, **kw):
    """Call the selected backend. Only 'auto' mode falls back to local."""
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
        print(f"[llm] server unreachable, using {FALLBACK_MODEL} on this Mac",
              flush=True)
        return fallback_client.chat.completions.create(
            model=model_for("local"), messages=messages, **kw)


def _flatten(message):
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
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            try:
                raw = json.load(f)
            except json.JSONDecodeError:
                return []
        history = [_flatten(m) for m in raw if isinstance(m, dict) and "role" in m]
        return [m for m in history if m["role"] != "system"]
    return []


_history_lock = threading.RLock()


SEND_WINDOW = HISTORY_TURNS * 2
RETAIN = HISTORY_TURNS * 6


def _window(history):
    msgs = [m for m in history if m.get("role") != "system"]
    if len(msgs) <= SEND_WINDOW:
        return msgs
    start = ((len(msgs) - SEND_WINDOW) // SEND_WINDOW) * SEND_WINDOW
    return msgs[start:]


def save_history(history):
    msgs = [m for m in history if m["role"] != "system"]
    if len(msgs) > RETAIN:
        msgs = msgs[-(RETAIN - SEND_WINDOW):]
    with _history_lock:
        tmp = f"{HISTORY_FILE}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(msgs, f, indent=2)
        os.replace(tmp, HISTORY_FILE)


def _extract_backend():
    if fallback_client is not None:
        return fallback_client, FALLBACK_MODEL
    return client, MODEL


def save_turn(user_text, assistant_text):
    assistant_text = (assistant_text or "").strip()
    if not assistant_text:
        return
    with _history_lock:
        history = _window(load_history())
        if user_text is not None:
            history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": assistant_text})
        save_history(history)
    if REMEMBER and user_text is not None:
        memory_extract.remember_async(*_extract_backend(), user_text, assistant_text)


def reset_history():
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
    """Save a turn that didn't come from the chat model, e.g. a screen look."""
    history = _window(load_history())
    history.append({"role": "user", "content": user_text})
    history.append({"role": "assistant", "content": assistant_text})
    save_history(history)


def llm_response(user_input):
    history = _window(load_history())
    history.append({"role": "user", "content": user_input})

    completion = get_reply([system_message()] + history)
    reply = (completion.choices[0].message.content or "").strip()

    history.append({"role": "assistant", "content": reply})
    save_history(history)

    if REMEMBER:
        memory_extract.remember_async(*_extract_backend(), user_input, reply)

    return reply


def get_reply_stream(messages, **kw):
    return chat_completion(
        messages,
        temperature=TEMPERATURE,
        max_tokens=MAX_TOKENS,
        stream=True,
        **kw,
    )


def _collect_tool_calls(delta, calls):
    for call in getattr(delta, "tool_calls", None) or []:
        slot = calls.setdefault(call.index, {"id": "", "name": "", "arguments": ""})
        if call.id:
            slot["id"] = call.id
        fn = getattr(call, "function", None)
        if fn is not None:
            if fn.name:
                slot["name"] = fn.name
            if fn.arguments:
                slot["arguments"] += fn.arguments


_tools_supported = True


def _rejects_tools(e):
    """True if the endpoint doesn't support tools (as opposed to being down)."""
    from openai import APIStatusError

    if not isinstance(e, APIStatusError):
        return False
    if e.status_code not in (400, 404, 422, 501):
        return False
    body = (str(getattr(e, "message", "")) or str(e)).lower()
    return "tool" in body or "function" in body or e.status_code in (404, 501)


def llm_stream(user_input=None, extra_system=None, use_tools=True):
    """Yield reply text as it arrives. The caller saves the turn with
    `save_turn`, since only it knows how much was actually spoken.

    `extra_system` is added to the system prompt for this call only.
    """
    history = _window(load_history())
    if user_input is not None:
        history.append({"role": "user", "content": user_input})

    system = system_message()
    if extra_system:
        system = {"role": "system", "content": system["content"] + extra_system}

    global _tools_supported

    messages = [system] + history
    offer = tools.definitions() if (use_tools and _tools_supported) else None

    for attempt in range(2):
        calls = {}
        try:
            stream = (get_reply_stream(messages, tools=offer, tool_choice="auto")
                      if offer else get_reply_stream(messages))
            for event in stream:
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                _collect_tool_calls(delta, calls)
                piece = getattr(delta, "content", None)
                if not piece:
                    continue
                yield piece
        except Exception as e:
            if offer is None or not _rejects_tools(e):
                raise
            print(f"[llm] endpoint rejected tool definitions "
                  f"({type(e).__name__}); continuing without them", flush=True)
            _tools_supported = False
            offer = None
            continue

        if not calls:
            return

        messages = messages + [{
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {"id": c["id"] or f"call_{i}", "type": "function",
                 "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                for i, c in sorted(calls.items())
            ],
        }]
        for i, call in sorted(calls.items()):
            result = tools.run(call["name"], call["arguments"])
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"] or f"call_{i}",
                "content": result,
            })
        offer = None
