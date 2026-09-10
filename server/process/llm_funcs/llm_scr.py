"""LLM conversation with on-disk history.

Speaks the OpenAI chat-completions API, which is the one dialect that OpenAI,
Ollama, llama.cpp, LM Studio and vLLM all implement. Set `llm.base_url` in
character_config.yaml to point at a local server instead of OpenAI.
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
from process.config import load_config, resolve
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

HISTORY_FILE = resolve(char_config["history_file"])
BASE_SYSTEM_PROMPT = char_config["presets"]["default"]["system_prompt"]


def system_message():
    """The stable half of the prompt: who she is, and what she remembers.

    Everything here changes rarely, which matters more than it looks. Servers
    cache the processed prefix of a prompt, and llama.cpp reprocesses from the
    first token that differs — so anything volatile at the front throws away
    the cache for the whole conversation behind it. Measured on this setup
    that is the difference between a first token in 0.2 s and one in 20 s.
    See `volatile_message`.
    """
    return {
        "role": "system",
        "content": BASE_SYSTEM_PROMPT + memory.as_prompt_block(),
    }


def volatile_message():
    """The half that changes every turn — the clock, and what is on her mind.

    Deliberately placed last, immediately before the newest user turn, so the
    cached prefix behind it stays intact. Putting the time of day in the
    system prompt instead meant the cache was invalidated every single minute,
    and every reply after the change of minute paid full prompt processing.
    """
    content = (persona.as_prompt_block() + ambient.as_prompt_block()).strip()
    return {"role": "system", "content": content} if content else None

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
    if FREQUENCY_PENALTY and "frequency_penalty" not in kw:
        kw["frequency_penalty"] = FREQUENCY_PENALTY
    if REPEAT_PENALTY and REPEAT_PENALTY != 1.0:
        extra = dict(kw.get("extra_body") or {})
        extra.setdefault("repeat_penalty", REPEAT_PENALTY)
        kw["extra_body"] = extra
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
                return []
        history = [_flatten(m) for m in raw if isinstance(m, dict) and "role" in m]
        return [m for m in history if m["role"] != "system"]
    return []


_history_lock = threading.RLock()


def save_history(history):
    trimmed = [m for m in history if m["role"] != "system"][-(HISTORY_TURNS * 2):]
    with _history_lock:
        tmp = f"{HISTORY_FILE}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(trimmed, f, indent=2)
        os.replace(tmp, HISTORY_FILE)


def save_turn(user_text, assistant_text):
    """Append one exchange, and distil anything worth keeping out of it.

    Every path that produces a reply ends here, including an interrupted one —
    which passes only the part she actually said out loud.
    """
    assistant_text = (assistant_text or "").strip()
    if not assistant_text:
        return
    with _history_lock:
        history = load_history()[-(HISTORY_TURNS * 2):]
        if user_text is not None:
            history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": assistant_text})
        save_history(history)
    if REMEMBER and user_text is not None:
        memory_extract.remember_async(client, MODEL, user_text, assistant_text)


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

    completion = get_reply([system_message()] + history)
    reply = (completion.choices[0].message.content or "").strip()

    history.append({"role": "assistant", "content": reply})
    save_history(history)

    if REMEMBER:
        memory_extract.remember_async(client, MODEL, user_input, reply)

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
    """Reassemble tool calls from stream deltas.

    They arrive in pieces like everything else: the name in one event, the
    JSON arguments a few characters at a time across the next several, keyed
    only by position in the list.
    """
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
    """Did the endpoint refuse the tool definitions, or just have a bad day?

    A 400 or 422 is the server reading the request and declining it, which is
    what an endpoint without tool support does. A timeout, a dropped socket or
    a 500 is a server that is unwell — retrying without tools would hide a
    real failure and cost her a capability permanently.
    """
    from openai import APIStatusError

    if not isinstance(e, APIStatusError):
        return False
    if e.status_code not in (400, 404, 422, 501):
        return False
    body = (str(getattr(e, "message", "")) or str(e)).lower()
    return "tool" in body or "function" in body or e.status_code in (404, 501)


def llm_stream(user_input=None, extra_system=None, use_tools=True):
    """Yield the reply as it is generated.

    Same conversation as `llm_response`, except the caller gets deltas and
    can start synthesizing before the model has finished. Saving the turn is
    deliberately not done here: being interrupted means the transcript should
    record what she said out loud, not what the model went on to write, and
    only the caller knows where the audio actually stopped. Call `save_turn`
    with that.

    `extra_system` is appended to the system prompt for this call only, which
    is how an unprompted opener and a tool result both get their instructions
    in without becoming part of her permanent character.
    """
    history = load_history()[-(HISTORY_TURNS * 2):]
    if user_input is not None:
        history.append({"role": "user", "content": user_input})

    system = system_message()
    if extra_system:
        system = {"role": "system", "content": system["content"] + extra_system}

    global _tools_supported

    volatile = volatile_message()
    tail = ([volatile] if volatile else [])
    if user_input is not None and history:
        messages = [system] + history[:-1] + tail + history[-1:]
    else:
        messages = [system] + history + tail
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
