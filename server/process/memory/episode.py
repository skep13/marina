"""What a stretch of conversation was about, kept after it scrolls away.

She is only ever sent the latest part of the conversation. When an older
block drops out of that window it used to be gone for good; now it is
boiled down to a few sentences first and kept as an episode (see
process.memory.store), and the latest few episodes sit in her prompt.

They are written the moment the window moves on, which is the one moment
the server has to reread her prompt anyway, so they cost nothing extra.
"""
import threading

from process import backend
from process.memory import store

PROMPT = """Below is part of a conversation between Marina and the friend she \
talks to. Write Marina's memory of it in two or three plain sentences, \
addressed to her as "you", calling the friend "they".

Say what was talked about and what happened, and keep straight whose things \
are whose: what they did, made, run or are going through is theirs; what \
Marina said about her own life is hers. Include anything left hanging that \
she might ask about later. No greetings, no opinions about the conversation, \
no quotes, nothing that isn't in it. If it was only small talk, one sentence \
is enough."""

MIN_CHARS = 200     # less than this isn't worth a memory
MAX_CHARS = 9000    # of conversation handed to the model


def _transcript(messages):
    lines = []
    for m in messages:
        text = m.get("content")
        if not isinstance(text, str) or not text.strip():
            continue
        who = "Marina" if m.get("role") == "assistant" else "They"
        lines.append(f"{who}: {' '.join(text.split())}")
    return "\n".join(lines)[-MAX_CHARS:]


def summarise(messages):
    """The episode text for these messages, or "" if there's nothing to keep
    or no model fit to write it."""
    text = _transcript(messages)
    if len(text) < MIN_CHARS:
        return ""
    try:
        from process.llm_funcs.llm_scr import chat_completion
        out = chat_completion(
            messages=[{"role": "system", "content": PROMPT},
                      {"role": "user", "content": text}],
            temperature=0.3, max_tokens=160, stream=False,
            frequency_penalty=0.0)
        if backend.on_fallback():
            return ""   # the small backup model gets who-did-what wrong
        return " ".join((out.choices[0].message.content or "").split())
    except Exception as e:
        print(f"[memory] couldn't summarise: {type(e).__name__}: {e}", flush=True)
        return ""


def remember_async(messages):
    """Summarise and store on a background thread."""
    messages = list(messages)
    if not messages:
        return

    def work():
        text = summarise(messages)
        if text and store.add(text, source=store.EPISODE):
            print(f"[memory] kept an episode: {text[:80]}…", flush=True)

    threading.Thread(target=work, daemon=True).start()
