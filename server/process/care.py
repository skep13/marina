"""Noticing when they are low, and being a friend about it.

Her usual voice is snarky, and she is allowed moods of her own. Neither
belongs in a reply to someone who is struggling. This looks at what they
have just said, and when it reads as low it puts a note on her newest
message: drop the teasing, stay with them, don't make it about herself.

It is deliberately plain pattern matching rather than a judgement by the
model, so it can't be talked out of or forgotten, and it works the same on
the small backup model. A miss costs little (she is warm anyway); it is
tuned to notice rather than to be sure.
"""
import re
import time

from process import state
from process.config import setting

LOOK_BACK = 3   # of their messages: once low, she stays gentle for a few

_LOW = re.compile(
    r"\b(depress(ed|ing)|miserable|hopeless|worthless|numb|empty inside|"
    r"feel(ing)? (so |really |pretty |kinda |a bit )?(low|down|empty|alone|lonely|awful|"
    r"terrible|like (shit|crap|a failure|a burden|nothing))|"
    r"hate (myself|my life|being me)|can'?t (do this|cope|keep going|go on|"
    r"stop crying|take (it|this))( anymore| any more)?|"
    r"(what'?s|whats|no) (the )?point|nobody (cares|would (care|notice))|"
    r"(i'?m|im|i am|i feel) (so |really |just )?(not ok(ay)?|done|falling apart|"
    r"breaking down|a mess|struggling|exhausted|so tired of (it|this|everything)|"
    r"tired of everything|sad|scared|lost)|"
    r"(been|was|i'?m|im) crying|panic attack|bad (day|night|week)|rough (day|night|week)|"
    r"everything('?s| is) (too much|falling apart|shit|pointless)|"
    r"(don'?t|dont) (know|see) (how|why) (i|to) (keep|carry|go) (going|on))\b", re.I)

_CRISIS = re.compile(
    r"\b(kill(ing)? myself|suicid\w*|end (it all|my life|things)|"
    r"(don'?t|dont|do not) want to (be here|be alive|live|exist|wake up)|"
    r"want(ed)? to (die|disappear|not exist)|wanna die|better off (dead|without me)|"
    r"hurt(ing)? myself|self[- ]?harm\w*|cut(ting)? myself|no reason to live|"
    r"not wanting to be here|wish i (was|were) (dead|gone|never born))\b", re.I)

# "this bug makes me want to die lol": said about a thing, with a laugh.
_JOKING = re.compile(r"\b(lol|lmao|haha+|jk|joking|kidding)\b|😂|🤣|💀", re.I)


def _text(m):
    c = m.get("content") if isinstance(m, dict) else m
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "").replace("’", "'")


HEARD_FOR = 20 * 60   # seconds a reading of how they sounded holds


def heard(how, now=None):
    """Note how they sounded, as judged after the last exchange (see
    process.memory.extract). The word list above misses quiet ways of saying
    it; this catches those one reply later."""
    if how in ("low", "crisis"):
        state.put("feeling", {"level": how, "until": (now or time.time()) + HEARD_FOR})


def _heard(now=None):
    got = state.get("feeling") or {}
    try:
        if float(got.get("until", 0)) > (now or time.time()):
            return got.get("level") if got.get("level") in ("low", "crisis") else ""
    except (TypeError, ValueError, AttributeError):
        pass
    return ""


def level(history, their_message=""):
    """"crisis", "low" or "" from their latest few messages."""
    return _worse(_said(history, their_message), _heard())


def _worse(a, b):
    return "crisis" if "crisis" in (a, b) else (a or b)


def _said(history, their_message=""):
    said = [_text(m) for m in history if isinstance(m, dict) and m.get("role") == "user"]
    if their_message:
        said.append(_text(their_message))
    recent = said[-LOOK_BACK:]
    found = ""
    for text in recent:
        if _CRISIS.search(text) and not _JOKING.search(text):
            return "crisis"
        if _LOW.search(text) and not _JOKING.search(text):
            found = "low"
    return found


def enabled():
    return bool(setting("care", "enabled", True))


def note(history, their_message=""):
    """The note for her newest message, or ""."""
    if not enabled():
        return ""
    how = level(history, their_message)
    if not how:
        return ""
    out = ("\n\n(Note to you, not from them: they sound low. For now, no teasing, "
           "no sarcasm and no bad mood of your own, even if you were annoyed a "
           "minute ago. Be quiet, warm and plain: stay with what they said, in a "
           "sentence or two. Don't fix it, don't list advice, don't cheer them "
           "up on a schedule, and no therapist phrases. Don't turn it to your own "
           "troubles or your own past; this is about them.")
    if how == "crisis":
        line = str(setting("care", "crisis_line", "") or "").strip()
        who = (f"someone they trust, or {line}" if line
               else "someone they trust, or a crisis line where they live")
        out += (" This is serious, so take it seriously: say you're glad they told "
                "you, and ask plainly whether they are safe right now. You care "
                "about them and you're staying, and you also want them to talk to "
                f"a real person today: {who}. Say that once, as someone who wants "
                "them around, not as a way of handing them off, and keep talking "
                "with them. If they say they are in danger right now, tell them "
                "to call emergency services.")
    return out + ")"
