"""LLM conversation with on-disk history.

Speaks the OpenAI chat-completions API, which is the one dialect that OpenAI,
Ollama, llama.cpp, LM Studio and vLLM all implement. Set `llm.base_url` in
character_config.yaml to point at a local server instead of OpenAI.
"""
import json
import os

from openai import OpenAI

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

client = OpenAI(api_key=API_KEY, base_url=BASE_URL)


def describe_endpoint():
    return BASE_URL or "https://api.openai.com/v1"


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
    return client.chat.completions.create(
        model=MODEL,
        messages=messages,
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
