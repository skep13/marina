"""Per-model habits, kept in check after the model has written.

Some models open every single reply with a *gesture*. One now and then
gives her avatar something to do; every time, it reads like a script.
With `llm.action_every: N` she may open with one at most once in every N
replies, and otherwise that opening gesture is left out. What she didn't
say isn't saved either, so the habit doesn't feed on itself.
"""
import re

from process.config import setting
from process.text_func.speech import _is_action

_OPENING = re.compile(r"^\s*\*(?!\s)([^*\n]{1,60})(?<!\s)\*[ \t]*\n*[ \t]*")
_LONGEST = 80  # past this, whatever it starts with isn't a short gesture


def _every():
    try:
        return max(0, int(setting("llm", "action_every", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _gesture(text):
    """The match for an opening gesture, None for anything else, including
    a word in italics for emphasis (*so* not fair)."""
    m = _OPENING.match(text or "")
    return m if m and _is_action(m.group(1), "italic") else None


def opens_with_action(text):
    return bool(_gesture(text))


def _her_replies(history):
    out = []
    for m in history or ():
        if m.get("role") != "assistant":
            continue
        c = m.get("content")
        if isinstance(c, list):
            c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
        if isinstance(c, str) and c.strip():
            out.append(c)
    return out


def may_open_with_action(history):
    """Whether this reply may start with a gesture."""
    n = _every()
    if n <= 1:
        return True
    recent = _her_replies(history)[-(n - 1):]
    return not any(opens_with_action(r) for r in recent)


def pace(reply, history):
    """The reply, without its opening gesture if she's had one too recently."""
    if not reply or may_open_with_action(history):
        return reply
    m = _gesture(reply)
    if not m or not reply[m.end():].strip():
        return reply   # a gesture and nothing else stays: it's all she said
    return reply[m.end():]


class Pacer:
    """`pace` for a reply arriving in pieces. Holds back only the start,
    until it is clear whether it opens with a gesture."""

    def __init__(self, history):
        self._allow = may_open_with_action(history)
        self._buf = ""
        self._decided = self._allow

    def feed(self, piece):
        if self._decided:
            return piece
        self._buf += piece
        text = self._buf.lstrip()
        if not text:
            return ""
        if not text.startswith("*") or text.startswith("**"):
            return self._release(self._buf)
        m = _OPENING.match(self._buf)
        # The gesture is complete once its closing * is followed by something
        # that isn't more whitespace.
        if m and m.end() < len(self._buf):
            if not _is_action(m.group(1), "italic"):
                return self._release(self._buf)
            return self._release(self._buf[m.end():])
        if len(text) > _LONGEST or (not m and re.match(r"^\s*\*[^*]*\n", self._buf)):
            return self._release(self._buf)
        return ""

    def flush(self):
        if self._decided:
            return ""
        return self._release(self._buf)   # all she said: keep it

    def _release(self, text):
        self._decided, self._buf = True, ""
        return text
