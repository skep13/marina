"""Chat completions client with on-disk history.

Works with anything OpenAI-compatible (OpenAI, Ollama, llama.cpp, LM Studio,
vLLM). Which endpoints exist and in what order is up to process.backend.
"""
import json
import os
import random
import re
import threading
import time

from openai import OpenAI, Timeout

from process import backend
from process import care
from process import gap
from process import mood

from process.backend import current as backend_current
from process.backend import mode as backend_mode
from process.backend import model_for
from process.backend import note_used
from process import config
from process import confirm
from process import shared
from process import room as her_room
from process.config import load_config, resolve_data
from process.memory import episode
from process.memory import extract as memory_extract
from process.memory import followup
from process.memory import lore
from process.memory import persona
from process.memory import recall
from process.memory import store as memory
from process.tools import context as ambient
from process.llm_funcs import fresh
from process.llm_funcs import style
from process.tools import registry as tools

char_config = load_config()

_llm = char_config.get("llm") or {}

MAX_TOKENS = _llm.get("max_tokens", 2048)

HISTORY_TURNS = int(_llm.get("history_turns", 12))

_HISTORY_BASE = resolve_data(char_config["history_file"])


def _history_file():
    """Each preset keeps its own conversation, so switching to a
    presentation personality doesn't bring the personal one along."""
    name = config.preset()
    if name == "default":
        return str(_HISTORY_BASE)
    return str(_HISTORY_BASE.with_name(f"{_HISTORY_BASE.stem}.{name}{_HISTORY_BASE.suffix}"))


def _temperature():
    return config.setting("llm", "temperature", 1.0)


def _remember():
    return bool(config.setting("llm", "remember", True))


def _recall():
    """Off keeps what she remembers out of the prompt, e.g. for a demo."""
    return bool(config.setting("llm", "recall", True))


def _stable_context():
    """The day and rough time, for when the exact clock isn't riding on her
    newest message. With the clock on this would only repeat it, and change
    the cached prompt six times a day to do so."""
    if ambient.ENABLED and ambient.SHOW_TIME:
        return ""
    from datetime import datetime
    now = datetime.now()
    h = now.hour
    part = ("the middle of the night" if h < 5 else "early morning" if h < 8 else
            "morning" if h < 12 else "afternoon" if h < 17 else
            "evening" if h < 22 else "late evening")
    return f"\n\nIt is {now:%A} {part}. Use this only if it is actually relevant."


LET_IT_GO = (
    "\n\nOnce you've made a joke or had your say about something, let it go: "
    "don't keep bringing the same topic or running joke back in later "
    "messages. When they change the subject, or say they've got it or don't "
    "need help, follow them and don't circle back."
)


def _style_note():
    """Words for the model in use, about habits of its own: one model
    narrates, another writes essays. Set as llm.style_note."""
    note = (config.setting("llm", "style_note", "") or "").strip()
    return f"\n\n{note}" if note else ""


def system_message():
    return {
        "role": "system",
        "content": (config.system_prompt()
                    + persona.profile_block()
                    + persona.examples_block()
                    + (memory.as_prompt_block() if _recall() else "")
                    + tools.prompt_addition()
                    + _stable_context()
                    + (ambient.NOTE_EXPLAINED if ambient.ENABLED else "")
                    + LET_IT_GO
                    + _style_note()),
    }


# Asked to introduce Hack Club, she gives this word for word instead of asking
# the model, so a live demo always gets the same intro.
INTRODUCTION = (
    "*waves* Hi everyone, I'm Marina. I was built as a Hack Club project for "
    "Stardance, sponsored by NASA, AMD and GitHub. Hack Club is a nonprofit "
    "that helps teenagers learn to code by building real projects, through "
    "school clubs, hackathons and big events like Outpost and Phantom."
)

_INTRODUCE = re.compile(r"\bintroduce hack ?club\b")


def scripted_reply(user_input):
    """The fixed reply for this message, if it has one."""
    if not isinstance(user_input, str):
        return None
    text = re.sub(r"[^a-z ]+", " ", user_input.lower())
    text = re.sub(r"\s+", " ", text)
    return INTRODUCTION if _INTRODUCE.search(text) else None


def _tool_rounds():
    """How many rounds of tool calls one reply may take before she has to
    answer. Work on her machine is a chain of them: run, read, fix, rerun.
    0 means no limit."""
    if not tools.wants_long_loop():
        return 1
    rounds = int(config.setting("llm", "max_tool_rounds", 0) or 0)
    return float("inf") if rounds <= 0 else rounds


class Activity(str):
    """Yielded by llm_stream around tool use. It is an empty string, so a
    caller that only joins up her words is unaffected; one that wants to show
    what she is doing reads `label` and `where` ("vm" for her machine, "mac"
    for theirs). With `confirm` set it is a question for them, answered at
    POST /confirm."""

    def __new__(cls, label, where, confirm=None):
        piece = super().__new__(cls, "")
        piece.label, piece.where, piece.confirm = label, where, confirm
        return piece


# The same call this many times running means she is stuck, not working.
STUCK_REPEATS = 3

# A reply that ends by promising to do something, when she could have.
_PROMISE = re.compile(
    r"\b(i'?ll|i will|let me|let'?s|i'?m (?:going|gonna) to|gonna|about to)\b",
    re.I)


_REQUEST = re.compile(
    r"\b(can you|could you|would you|will you|please|pls|go ahead|do it|try|make|create|"
    r"build|write|install|set up|setup|fix|check|look (?:at|over|into)|open|run|update|"
    r"change|add|remove|delete|move|rename|show me|find|search|type|theme|start|finish)\b",
    re.I)


def _asked_for_work(user_input):
    """Whether their message asked her to do something. Only then is a plan
    without action worth holding her to; in ordinary chat, "let me think"
    is just talk."""
    if isinstance(user_input, list):
        user_input = " ".join(p.get("text", "") for p in user_input if isinstance(p, dict))
    return bool(user_input) and bool(_REQUEST.search(str(user_input)))


def _promised(text):
    """True if the last sentence of a reply says she is about to do something."""
    tail = re.split(r"(?<=[.!?])\s+", (text or "").strip())[-1]
    return bool(_PROMISE.search(tail.replace("\u2019", "'")))


STICKY = float(_llm.get("fallback_sticky_seconds", 30))

THINKING = bool(_llm.get("thinking", False))

SEED = _llm.get("seed")

REPEAT_PENALTY = float(_llm.get("repeat_penalty", 1.12))
FREQUENCY_PENALTY = float(_llm.get("frequency_penalty", 0.35))
# For chat only (work mode turns penalties off): presence_penalty pushes away
# from any word already said; DRY (llama.cpp) from repeating runs of words,
# which is what a stuck opener or template is. 0 leaves them off.
PRESENCE_PENALTY = float(_llm.get("presence_penalty", 0.0))
DRY_MULTIPLIER = float(_llm.get("dry_multiplier", 0.0))



def _client(b):
    # A box that is off should fail fast so the next one gets a turn, but a
    # model that is still loading needs the full read timeout.
    return OpenAI(api_key=b["api_key"], base_url=b["base_url"],
                  timeout=Timeout(b["timeout"], connect=5.0), max_retries=0)


_clients = {b["name"]: _client(b) for b in backend.BACKENDS}
client = _clients["server"]

_down_until = {}


def describe_endpoint():
    b = backend.get(backend_current())
    return (b and b["base_url"]) or "https://api.openai.com/v1"


def active_model():
    return model_for()


def active_endpoint():
    return backend_current()


def _order():
    """Backends to try for this call, best first."""
    m = backend_mode()
    if m != "auto":
        return [m]
    now = time.time()
    up = [n for n in backend.NAMES if _down_until.get(n, 0) <= now]
    # If everything is marked down, try them all again rather than giving up.
    return up or list(backend.NAMES)


def _pick():
    which = _order()[0]
    return _clients[which], model_for(which), which


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
    chatting = kw.get("frequency_penalty") != 0.0  # work mode sets it to 0
    if chatting and PRESENCE_PENALTY and "presence_penalty" not in kw:
        kw["presence_penalty"] = PRESENCE_PENALTY
    if chatting and DRY_MULTIPLIER:
        extra = dict(kw.get("extra_body") or {})
        extra.setdefault("dry_multiplier", DRY_MULTIPLIER)
        extra.setdefault("dry_base", 1.75)
        extra.setdefault("dry_allowed_length", 3)
        kw["extra_body"] = extra
    if FREQUENCY_PENALTY and "frequency_penalty" not in kw:
        kw["frequency_penalty"] = FREQUENCY_PENALTY
    if REPEAT_PENALTY and REPEAT_PENALTY != 1.0:
        extra = dict(kw.get("extra_body") or {})
        extra.setdefault("repeat_penalty", REPEAT_PENALTY)
        kw["extra_body"] = extra
    return kw


ON_BACKUP = (
    "\n\nRight now the machine you normally think with isn't answering, so you "
    "are running on a small backup and are not as sharp as usual. Keep to one "
    "or two short sentences. Don't attempt anything involved, and never claim "
    "to have done, checked or remembered something. If they want something "
    "that needs your tools or a proper think, tell them plainly, as yourself, "
    "that your brain is offline at the moment."
)


def _is_backup(which):
    return backend_mode() == "auto" and which == "local" and len(backend.NAMES) > 1


def _for_backup(messages, kw):
    """The same request, cut down for the small backup model: no tools, which
    it calls at random, and a word to her about the state she is in."""
    kw = {k: v for k, v in kw.items() if k not in ("tools", "tool_choice")}
    first = messages[0] if messages else None
    if (first and first.get("role") == "system" and _recall()
            and str(first.get("content", "")).startswith(config.system_prompt())):
        messages = [{**first, "content": first["content"] + ON_BACKUP}] + list(messages[1:])
    return messages, kw


def chat_completion(messages, **kw):
    """Call the selected backend. In auto mode, fall through to the next one
    whenever a backend can't be reached."""
    from openai import APIConnectionError, APITimeoutError

    routed = kw.pop("_model", None)
    kw = _request_extras(kw)
    order = _order()
    for i, which in enumerate(order):
        send, send_kw = _for_backup(messages, kw) if _is_backup(which) else (messages, kw)
        try:
            # A route only ever moves work on lab3; the backup keeps its own model.
            model = routed if (routed and which == "server") else model_for(which)
            out = _clients[which].chat.completions.create(
                model=model, messages=send, **send_kw)
        except (APIConnectionError, APITimeoutError):
            if i == len(order) - 1:
                raise
            _down_until[which] = time.time() + STICKY
            nxt = order[i + 1]
            print(f"[llm] {backend.label(which)} unreachable, trying "
                  f"{backend.label(nxt)} ({model_for(nxt)})", flush=True)
            continue
        if _down_until.pop(which, None):
            print(f"[llm] {backend.label(which)} is back", flush=True)
        note_used(which)
        return out


def _flatten(message):
    content = message.get("content")
    if isinstance(content, list):
        content = "".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        )
    elif not isinstance(content, str):
        content = str(content)
    out = {"role": message["role"], "content": content}
    if isinstance(message.get("at"), str):
        out["at"] = message["at"]   # when it was said; see process.gap
    return out


def _bare(history):
    """The conversation as the model is sent it: who and what, without the
    times kept alongside."""
    return [{k: v for k, v in m.items() if k != "at"} for m in history]


def _stamped(messages):
    from datetime import datetime
    now = datetime.now().astimezone().isoformat(timespec="seconds")
    return [m if m.get("at") else {**m, "at": now} for m in messages]


def _shared_history():
    """Only the personal conversation is shared. A presentation keeps its
    own, so guests never see what you texted her."""
    return shared.enabled() and config.preset() == "default"


def load_history():
    """The conversation, from the shared home if there is one."""
    if _shared_history():
        msgs = shared.call("GET", "/shared/history")
        if isinstance(msgs, list):
            history = [_flatten(m) for m in msgs if isinstance(m, dict) and "role" in m]
            save_history(history)  # the copy used if the home is down
            return [m for m in history if m["role"] != "system"]
    return load_local_history()


def load_local_history():
    path = _history_file()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
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
        path = _history_file()
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(msgs, f, indent=2)
        os.replace(tmp, path)


def _extract_backend():
    c, model, _which = _pick()
    return c, model


def append_local(messages):
    """Add messages to this bridge's own conversation file. When that moves
    her window on, what has just scrolled out of it is kept as an episode."""
    with _history_lock:
        everything = load_local_history()
        history = _window(everything)
        gone = everything[:len(everything) - len(history)]
        history.extend(messages)
        save_history(history)
    if gone and _remember():
        episode.remember_async(gone)


def append_history(messages):
    """Add messages to the conversation. Appending, rather than saving the
    whole thing, is what lets the desktop and Telegram both write to the
    shared one without either losing what the other just said."""
    messages = _stamped(messages)
    if _shared_history():
        if shared.call("POST", "/shared/history", {"messages": messages}) is not None:
            return
    append_local(messages)


_STRAY_START = re.compile(r"^[.,;:]\s*(?=[A-Za-z*])")


def save_turn(user_text, assistant_text):
    assistant_text = _STRAY_START.sub("", (assistant_text or "").strip())
    if not assistant_text:
        return
    turn = [] if user_text is None else [{"role": "user", "content": user_text}]
    append_history(turn + [{"role": "assistant", "content": assistant_text}])
    if _remember() and user_text is not None and not backend.on_fallback():
        memory_extract.remember_async(*_extract_backend(), user_text, assistant_text)


def reset_history():
    lore.reset()
    recall.reset()
    followup.reset()
    mood.reset()
    if _shared_history():
        shared.call("DELETE", "/shared/history")
    reset_local_history()


def reset_local_history():
    path = _history_file()
    if os.path.exists(path):
        os.remove(path)


def get_reply(messages):
    return chat_completion(
        messages,
        temperature=_temperature(),
        max_tokens=MAX_TOKENS,
        stream=False,
    )


def note_exchange(user_text, assistant_text):
    """Save a turn that didn't come from the chat model, e.g. a screen look."""
    append_history([{"role": "user", "content": user_text},
                    {"role": "assistant", "content": assistant_text}])


def _plain(user_input):
    """The words of a message that may be text and images."""
    if isinstance(user_input, list):
        return " ".join(p.get("text", "") for p in user_input if isinstance(p, dict))
    return user_input or ""


def turn_notes(history, user_input=None):
    """Everything that rides on her newest message for this reply only:
    memories that have come up, something to ask about, her own day, her
    mood, and what to do differently from her last few replies. None of it
    is saved, and none of it goes in the system prompt.

    When they are low, the notes that make her lively are left out and one
    about being a friend goes last, where it carries most weight."""
    text = _plain(user_input)
    gentle = care.note(history, text)
    personal = _recall() and not gentle
    working = _asked_for_work(user_input)
    feeling = mood.note(text) if personal else ""   # her mood moves either way
    # Most important first. Each of these is reasonable alone; five at once
    # and she answers the notes instead of them, so only the first few that
    # have something to say are kept.
    notes = []
    room = max(1, int(config.setting("notes", "max", 2)))

    def offer(make):
        if len(notes) < room:
            note = make()
            if note:
                notes.append(note)

    if personal:
        offer(lambda: followup.note(their_message=text))
    offer(lambda: lore.note(history, text))
    offer(lambda: her_room.home_note(text))
    if personal:
        offer(lambda: gap.note(history))
        offer(lambda: recall.note(text))
        if not working and user_input is not None:
            offer(lambda: fresh.steer(history, text))
        offer(lambda: feeling)
    offer(lambda: fresh.note(history, text))
    if personal and not working:
        offer(lambda: persona.as_prompt_block(roll=None if user_input is not None else 0.0))
    return "".join(notes) + gentle


def llm_response(user_input):
    history = _merge_her_runs(_window(load_history()))
    history.append({"role": "user", "content": user_input + turn_notes(history, user_input)})

    reply = scripted_reply(user_input)
    if reply is None:
        completion = get_reply([system_message()] + _bare(history))
        reply = style.pace((completion.choices[0].message.content or "").strip(), history)

    append_history([{"role": "user", "content": user_input},
                    {"role": "assistant", "content": reply}])

    if _remember() and not backend.on_fallback():
        memory_extract.remember_async(*_extract_backend(), user_input, reply)

    return reply


# Once she is using tools she is working, not chatting: steadier sampling,
# no penalty on repeating herself (typing exact text, writing JSON), and
# room to think before each step. Her first round, and so every ordinary
# chat, keeps her personality settings.
WORK_TEMPERATURE = float(_llm.get("work_temperature", 0.6))
WORK_THINKING = bool(_llm.get("think_while_working", True))
WORK_MAX_TOKENS = int(_llm.get("work_max_tokens", 4096))


# Qwen's recommended values; Gemma wants top_k 64 and top_p 0.95.
WORK_TOP_K = int(_llm.get("work_top_k", 20))
WORK_TOP_P = float(_llm.get("work_top_p", 0.8))


def _work_settings():
    extra = {"top_k": WORK_TOP_K, "repeat_penalty": 1.0}
    if WORK_THINKING:
        extra["chat_template_kwargs"] = {"enable_thinking": True}
    return {"temperature": WORK_TEMPERATURE, "top_p": WORK_TOP_P, "frequency_penalty": 0.0,
            "max_tokens": WORK_MAX_TOKENS, "extra_body": extra}


KEEP_FULL_RESULTS = 4
OLD_RESULT_CHARS = 300
# Shortening changes text the server has cached, so it rereads from there;
# only worth it once a job has grown big (about 15K tokens).
SHORTEN_FROM_CHARS = 60000


def _shorten_old_results(messages):
    """On a long job, keep only the latest few tool results in full. Older
    screen descriptions and command output are out of date anyway, and
    carrying them all fills her context until she loses the thread."""
    if sum(len(str(m.get("content") or "")) for m in messages) < SHORTEN_FROM_CHARS:
        return messages
    results = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
    old = set(results[:-KEEP_FULL_RESULTS])
    out = []
    for i, m in enumerate(messages):
        text = m.get("content") or ""
        if i in old and len(text) > OLD_RESULT_CHARS:
            m = {**m, "content": text[:OLD_RESULT_CHARS] + " … (older result, shortened)"}
        out.append(m)
    return out


# Like the Room of AIs: work on certain kinds of request goes to the model
# best at it. Each route in `llm.routes` has a `match` regex, tried against
# their message, and the `model` (and optionally `temperature`) to work
# with. Only her working rounds move, the ones after she has started using
# tools, so ordinary chat that happens to mention code stays on her own
# model and never pays for a model swap. First match wins.
ROUTES = []
for _r in _llm.get("routes") or []:
    try:
        ROUTES.append({**_r, "_re": re.compile(_r["match"], re.I)})
    except (KeyError, TypeError, re.error) as _e:
        print(f"[llm] ignoring a route that doesn't work: {_e}", flush=True)


def route_for(user_input):
    if isinstance(user_input, list):
        user_input = " ".join(p.get("text", "") for p in user_input if isinstance(p, dict))
    text = str(user_input or "")
    for r in ROUTES:
        if r.get("model") and r["_re"].search(text):
            return r
    return None


def get_reply_stream(messages, working=False, route=None, **kw):
    settings = _work_settings() if working else {
        "temperature": _temperature(), "max_tokens": MAX_TOKENS}
    if working and route:
        settings["_model"] = route["model"]
        if route.get("temperature") is not None:
            settings["temperature"] = float(route["temperature"])
    return chat_completion(messages, stream=True, **settings, **kw)


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


class _Unspoken:
    """Takes reasoning out of streamed text. A thinking model's server
    normally keeps it apart from the reply; when it doesn't, it arrives
    inside <think> tags, and she would say it aloud."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self):
        self._buf = ""
        self._inside = False

    def feed(self, piece):
        self._buf += piece
        out = []
        while True:
            if self._inside:
                end = self._buf.find(self.CLOSE)
                if end < 0:
                    # Keep only what could be the start of the closing tag.
                    self._buf = self._buf[-(len(self.CLOSE) - 1):]
                    break
                self._buf = self._buf[end + len(self.CLOSE):]
                self._inside = False
                continue
            start = self._buf.find(self.OPEN)
            if start >= 0:
                out.append(self._buf[:start])
                self._buf = self._buf[start + len(self.OPEN):]
                self._inside = True
                continue
            hold = 0   # a tag may be split across pieces: keep back "<thi"
            for n in range(min(len(self.OPEN) - 1, len(self._buf)), 0, -1):
                if self.OPEN.startswith(self._buf[-n:]):
                    hold = n
                    break
            cut = len(self._buf) - hold
            out.append(self._buf[:cut])
            self._buf = self._buf[cut:]
            break
        return "".join(out)

    def flush(self):
        out, self._buf = ("" if self._inside else self._buf), ""
        return out


def _after_reasoning(text):
    """Drop reasoning whose opening tag was in the prompt, so only its
    closing tag shows up in what she wrote."""
    return text.rsplit("</think>", 1)[-1] if "</think>" in text else text


_LIKE_A_CALL = re.compile(r"\{|<tool_call|<function|```(?:json)?\s*\{")


def _call_in_text(text, offer):
    """The tool call a reply is, when the model wrote one out as text
    ({"name": ..., "arguments": ...}) instead of making it. None unless the
    whole reply is exactly that and names a tool she has."""
    body = re.sub(r"^```(?:json)?|```$|</?tool_call>", "", text.strip(), flags=re.M).strip()
    if not offer or not body.startswith("{"):
        return None
    try:
        data = json.loads(body)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    name = data.get("name")
    arguments = data.get("arguments", data.get("parameters", {}))
    known = {t["function"]["name"] for t in offer}
    if name not in known:
        return None
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments)
    return {"id": "", "name": name, "arguments": arguments}


def _merge_her_runs(history):
    """Several of her messages in a row (texts they haven't answered yet)
    become one, as servers only accept one assistant turn at a time."""
    out = []
    for m in history:
        if (out and m.get("role") == "assistant" == out[-1].get("role")
                and not m.get("tool_calls") and not out[-1].get("tool_calls")
                and isinstance(m.get("content"), str) and isinstance(out[-1].get("content"), str)):
            out[-1] = {**out[-1], **m, "content": out[-1]["content"] + "\n\n" + m["content"]}
        else:
            out.append(m)
    return out


def llm_stream(user_input=None, extra_system=None, use_tools=True, history=None):
    """Yield reply text as it arrives, with her opening gesture paced
    (see style). Arguments as for `_stream`."""
    past = _window(load_history()) if history is None else history
    pacer = style.Pacer(past)
    for piece in _stream(user_input, extra_system, use_tools, history):
        if isinstance(piece, Activity):
            held = pacer.flush()
            if held:
                yield held
            yield piece
        elif piece:
            piece = pacer.feed(piece)
            if piece:
                yield piece
        else:
            yield piece   # nothing said: the caller's chance to notice a hang-up
    held = pacer.flush()
    if held:
        yield held


def _stream(user_input=None, extra_system=None, use_tools=True, history=None):
    """Yield reply text as it arrives. The caller saves the turn with
    `save_turn`, since only it knows how much was actually spoken.

    `extra_system` is added to the system prompt for this call only.
    `history` replaces her own conversation, for a chat that keeps its own
    threads, like Open WebUI.
    """
    scripted = scripted_reply(user_input)
    if scripted is not None:
        yield scripted
        return
    history = _window(load_history()) if history is None else list(history)
    # Servers refuse a conversation that ends on two of her messages, and
    # some refuse two in a row anywhere, so her unanswered ones run together.
    history = _merge_her_runs(history)
    if user_input is not None:
        # The clock goes on this message only, never into the saved history
        # or the system prompt, so the cached prefix stays the same.
        note = ambient.as_note() + turn_notes(history, user_input)
        if isinstance(user_input, list):  # text and images, from a chat UI
            content = user_input + ([{"type": "text", "text": note.strip()}] if note else [])
        else:
            content = user_input + note
        history.append({"role": "user", "content": content})
    else:
        # Speaking up unprompted. The conversation can't end on her own
        # message, so the app's nudge goes in as a turn of its own (never
        # saved).
        history.append({"role": "user", "content":
                        "(No new message from them; the app is giving you a chance "
                        "to speak first.)" + ambient.as_note() + turn_notes(history)})

    system = system_message()
    if extra_system:
        system = {"role": "system", "content": system["content"] + extra_system}

    global _tools_supported

    messages = [system] + _bare(history)
    offer = tools.definitions() if (use_tools and _tools_supported) else None

    rounds = _tool_rounds()
    route = route_for(user_input) if offer else None
    if route:
        print(f"[llm] work on this goes to {route['model']}", flush=True)
    done_rounds = 0
    last_calls = []
    nudged = False
    consented = set()  # things they have said yes to for this reply
    retried_garbled = False
    while True:
        calls = {}
        said = []
        working = done_rounds > 0
        # Whether this round's words go out as they arrive. While she is
        # working they wait: if the round ends in another tool call they
        # were a note to herself ("now let me check the config"), and only
        # the round that ends the job is her talking to them. A round that
        # opens like a tool call written out as text waits too.
        aloud = False if working else None
        unspoken = _Unspoken()
        try:
            routed = {"route": route} if route else {}
            stream = (get_reply_stream(messages, working, tools=offer, tool_choice="auto", **routed)
                      if offer else get_reply_stream(messages, working))
            for event in stream:
                if not event.choices:
                    continue
                delta = event.choices[0].delta
                _collect_tool_calls(delta, calls)
                piece = unspoken.feed(getattr(delta, "content", None) or "")
                if not piece:
                    continue
                said.append(piece)
                if aloud is None:
                    start = "".join(said).lstrip()
                    if not start:
                        continue
                    aloud = not _LIKE_A_CALL.match(start)
                    piece = "".join(said)
                if aloud:
                    yield piece
            tail = unspoken.flush()
            if tail:
                said.append(tail)
                if aloud:
                    yield tail
        except Exception as e:
            if offer is None or not _rejects_tools(e):
                raise
            print(f"[llm] endpoint rejected tool definitions "
                  f"({type(e).__name__}); continuing without them", flush=True)
            _tools_supported = False
            offer = None
            continue

        if not aloud and said:
            text = _after_reasoning("".join(said))
            written = None if calls else _call_in_text(text, offer)
            if written:
                # A tool call that came as text instead of as a call: run it.
                calls, text = {0: written}, ""
            elif not calls and tools.garbled(text):
                # Half a tool call and nothing else. Have her answer in words.
                print("[llm] a mangled tool call instead of a reply", flush=True)
                if retried_garbled:
                    return
                retried_garbled, offer = True, None
                continue
            if calls:
                if text.strip():
                    print(f"[llm] (to herself, working) {text.strip()[:200]}", flush=True)
            elif text:
                yield text
            said = [text]

        if not calls and offer is not None and not nudged and tools.wants_long_loop() \
                and _asked_for_work(user_input) and _promised("".join(said)):
            # She said what she was about to do and stopped. Hold her to it
            # once, rather than leaving them with a plan and no work.
            nudged = True
            print("[llm] she described a plan without doing it; nudging", flush=True)
            yield "\n\n"
            messages = messages + [
                {"role": "assistant", "content": "".join(said)},
                {"role": "user", "content": "(go ahead and do it now, with your tools)"},
            ]
            continue

        if not calls or offer is None:
            return

        messages = messages + [{
            "role": "assistant",
            "content": "".join(said) or None,
            "tool_calls": [
                {"id": c["id"] or f"call_{i}", "type": "function",
                 "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}}
                for i, c in sorted(calls.items())
            ],
        }]
        for i, call in sorted(calls.items()):
            name, arguments = call["name"], call["arguments"]
            label, where = tools.describe(name, arguments)
            if label:
                yield Activity(label, where)
            question = tools.needs_ok(name, arguments, consented)
            if question:
                ask = confirm.request(question)
                yield Activity(question, where, confirm=ask.id)
                if confirm.wait(ask):
                    consented.add(tools.consent_key(name))
                    result = tools.run(name, arguments)
                else:
                    print(f"[llm] they didn't allow: {question}", flush=True)
                    result = ("They didn't allow that, so it wasn't done. Don't try "
                              "another way round it; say so and ask what they'd like.")
            else:
                result = tools.run(name, arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": call["id"] or f"call_{i}",
                "content": result,
            })
        done_rounds += 1
        messages = _shorten_old_results(messages)
        # Nothing to say, but a chance for the caller to notice it was hung
        # up on; without it a long run of tool calls never yields, and she
        # would carry on working for nobody.
        yield ""
        signature = json.dumps([(c["name"], c["arguments"]) for _, c in sorted(calls.items())])
        last_calls = (last_calls + [signature])[-STUCK_REPEATS:]
        stuck = len(last_calls) == STUCK_REPEATS and len(set(last_calls)) == 1
        if stuck:
            print(f"[llm] same tool call {STUCK_REPEATS} times running; "
                  "making her answer", flush=True)
        if done_rounds >= rounds or stuck:
            # No more tools, so the next pass has to answer.
            offer = None
