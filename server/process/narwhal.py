"""Narwhal from the Moonwake app: a plain chat with the narwhal model on the
same llama-swap her bridge already talks to, so the phone needs no key of
its own and nothing new is opened to the network.

`stream` is the original stateless call: the app sends the conversation
whole and nothing is kept. Synced sessions (kept on lab3, shared by the
phone and the Mac, watchable live) are in process/narwhal_sessions.py and
use `events` below. Narwhal shares none of Marina's memory or history.

Events, one JSON object per line:
  {"type": "start", "model": ...}
  {"type": "think", "text": ...}    reasoning, as it comes
  {"type": "text", "text": ...}     the answer, as it comes
  {"type": "done", "seconds": ..., "think_seconds": ..., "chars": ...}
  {"type": "stopped", "seconds": ...}
  {"type": "error", "message": ...}
"""

import json
import time

from process import config as cfg

# How much of the conversation goes to the model each turn.
MAX_MESSAGES = 40
MAX_CHARS = 60_000


def model():
    return str(cfg.setting("narwhal", "model", "narwhal") or "narwhal")


def _system():
    return str(cfg.setting("narwhal", "system", "") or "").strip()


def clean(messages):
    """Only user and assistant turns, as text, newest kept within the caps."""
    out = []
    for m in messages or []:
        if not isinstance(m, dict) or m.get("role") not in ("user", "assistant"):
            continue
        text = str(m.get("content") or "").strip()
        if text:
            out.append({"role": m["role"], "content": text})
    out = out[-MAX_MESSAGES:]
    while len(out) > 1 and sum(len(m["content"]) for m in out) > MAX_CHARS:
        out.pop(0)
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _line(event):
    return json.dumps(event, ensure_ascii=False) + "\n"


class _ThinkSplitter:
    """Splits <think>...</think> out of streamed content, for servers that
    leave reasoning inline instead of in reasoning_content. Tags can arrive
    split across chunks, so a possible partial tag is held back."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self.inside = False
        self.buf = ""

    def feed(self, text):
        self.buf += text
        out = []
        while self.buf:
            tag = self.CLOSE if self.inside else self.OPEN
            i = self.buf.find(tag)
            if i >= 0:
                if i:
                    out.append(("think" if self.inside else "text", self.buf[:i]))
                self.buf = self.buf[i + len(tag):]
                self.inside = not self.inside
                continue
            # Keep back anything that could be the start of the tag.
            keep = 0
            for k in range(1, len(tag)):
                if self.buf.endswith(tag[:k]):
                    keep = k
            emit = self.buf[:len(self.buf) - keep]
            if emit:
                out.append(("think" if self.inside else "text", emit))
            self.buf = self.buf[len(emit):]
            break
        return out

    def flush(self):
        rest, self.buf = self.buf, ""
        return [("think" if self.inside else "text", rest)] if rest else []


def events(client, msgs, model_id, system="", error_message=str, cancel=None,
           thinking=True, tools=None, run_tool=None, max_rounds=5):
    """Yields event dicts for one reply from `model_id` to the cleaned
    messages `msgs`. `cancel` is checked between chunks; when it returns true
    the reply ends with a "stopped" event.

    thinking=False asks the model to answer straight away (Quick).
    With `tools` and `run_tool(name, args) -> (step, result)`, the model may
    call them (web search); each call shows as a step in the reasoning and
    the reply carries on with the result, up to `max_rounds` times."""
    msgs = list(msgs)
    if system:
        msgs = [{"role": "system", "content": system}] + msgs
    started = time.monotonic()
    st = {"think_started": None, "think_ended": None, "first_token": None, "chars": 0,
          "think_chars": 0, "usage": {}, "timings": {}, "completion": 0}
    extra = {} if thinking else {"chat_template_kwargs": {"enable_thinking": False}}
    try:
        for rnd in range(max_rounds + 1):
            use_tools = tools if tools and run_tool and rnd < max_rounds else None
            calls = {}
            stopped = yield from _one_pass(client, msgs, model_id, extra, use_tools, cancel, st, calls)
            if stopped:
                yield {"type": "stopped", "seconds": round(time.monotonic() - started, 1)}
                return
            if not calls:
                break
            todo = [calls[i] for i in sorted(calls)]
            msgs.append({"role": "assistant", "content": "",
                         "tool_calls": [{"id": c["id"] or f"call_{rnd}_{i}", "type": "function",
                                         "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                                        for i, c in enumerate(todo)]})
            for i, c in enumerate(todo):
                if cancel and cancel():
                    yield {"type": "stopped", "seconds": round(time.monotonic() - started, 1)}
                    return
                step, result = run_tool(c["name"], c["args"])
                yield {"type": "think", "text": "\n" + step + "\n"}
                msgs.append({"role": "tool", "tool_call_id": c["id"] or f"call_{rnd}_{i}", "content": result})
    except Exception as e:  # noqa: BLE001 - shown to the user, not raised
        yield {"type": "error", "message": error_message(e)}
        return
    end = time.monotonic()
    ts, te = st["think_started"], st["think_ended"]
    thought = ((te or end) - ts) if ts else 0
    usage = dict(st["usage"])
    if st["completion"]:
        usage["completion_tokens"] = st["completion"]
    yield {"type": "done", "seconds": round(end - started, 1),
           "think_seconds": round(thought, 1), "chars": st["chars"],
           **_speed(usage, st["timings"], st["chars"] + st["think_chars"], st["first_token"], end)}


def _one_pass(client, msgs, model_id, extra, tools, cancel, st, calls):
    """Streams one model call, yielding think/text events and filling
    `calls` with any tool calls. Returns True if it was stopped."""
    kw = {"model": model_id, "messages": msgs, "stream": True, "stream_options": {"include_usage": True}}
    if extra:
        kw["extra_body"] = extra
    if tools:
        kw["tools"] = tools
    response = client.chat.completions.create(**kw)
    split = _ThinkSplitter()
    for chunk in response:
        u = getattr(chunk, "usage", None)
        if u:
            st["usage"] = {"prompt_tokens": getattr(u, "prompt_tokens", None),
                           "completion_tokens": getattr(u, "completion_tokens", None)}
            st["completion"] += getattr(u, "completion_tokens", None) or 0
        t = (getattr(chunk, "model_extra", None) or {}).get("timings")
        if isinstance(t, dict):
            st["timings"] = t
        if cancel and cancel():
            close = getattr(response, "close", None)
            if close:
                close()
            return True
        if not getattr(chunk, "choices", None):
            continue
        delta = chunk.choices[0].delta
        for tc in getattr(delta, "tool_calls", None) or []:
            c = calls.setdefault(getattr(tc, "index", 0) or 0, {"id": "", "name": "", "args": ""})
            c["id"] = getattr(tc, "id", None) or c["id"]
            fn = getattr(tc, "function", None)
            if fn is not None:
                c["name"] = getattr(fn, "name", None) or c["name"]
                c["args"] += getattr(fn, "arguments", None) or ""
        parts = []
        mx = getattr(delta, "model_extra", None) or {}
        reasoning = getattr(delta, "reasoning_content", None) or mx.get("reasoning_content")
        if reasoning:
            parts.append(("think", reasoning))
        if getattr(delta, "content", None):
            parts.extend(split.feed(delta.content))
        for kind, text in parts:
            yield from _out(st, kind, text)
    for kind, text in split.flush():
        yield from _out(st, kind, text)
    return False


def _out(st, kind, text):
    st["first_token"] = st["first_token"] or time.monotonic()
    if kind == "think":
        st["think_chars"] += len(text)
        st["think_started"] = st["think_started"] or time.monotonic()
    else:
        if st["think_started"] and not st["think_ended"]:
            st["think_ended"] = time.monotonic()
        st["chars"] += len(text)
    yield {"type": kind, "text": text}


def _speed(usage, timings, out_chars, first_token, end):
    """Token counts and generation speed for the meter. llama-server sends
    exact numbers (usage, and timings with predicted_per_second); anything
    missing is estimated at ~4 characters a token and marked as such."""
    out = {}
    prompt = usage.get("prompt_tokens") or timings.get("prompt_n")
    completion = usage.get("completion_tokens") or timings.get("predicted_n")
    estimated = False
    if not completion and out_chars:
        completion, estimated = max(1, round(out_chars / 4)), True
    if prompt:
        out["prompt_tokens"] = int(prompt)
    if completion:
        out["completion_tokens"] = int(completion)
    rate = timings.get("predicted_per_second")
    if not rate and completion and first_token and end - first_token > 0.05:
        rate = completion / (end - first_token)
    if rate:
        out["tok_s"] = round(float(rate), 1)
    if estimated:
        out["estimated"] = True
    return out


def stream(client, messages, error_message=str):
    """Yields NDJSON lines for one Narwhal reply (the old, stateless call:
    the app sends the whole conversation and nothing is kept)."""
    msgs = clean(messages)
    if not msgs:
        yield _line({"type": "error", "message": "Nothing to send."})
        return
    yield _line({"type": "start", "model": model()})
    for ev in events(client, msgs, model(), _system(), error_message):
        yield _line(ev)
