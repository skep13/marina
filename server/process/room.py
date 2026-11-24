"""One Marina in two places: at home with them, and in the Room of AIs.

The room runs her through its own connector, with a persona made for the
room and its own model routing, so she would otherwise be two people who
never hear of each other. This joins them up, in both directions, through
her bridge, which is where her life is kept:

  GET  /room/context  what the room connector puts in front of her: her own
                      fixed facts and what is going on in her life lately,
                      plus her diary of earlier room sessions (the hub only
                      shows the last few messages). Nothing about their life:
                      the room persona keeps her owner's private life out.
  POST /room/note     the connector, after each message or piece of work she
                      posts there. It goes in a short diary.

At home, the diary rides on her newest message when they ask about the room
or what she has been up to, so she can talk about it like something she did.
"""
import re
import time
from datetime import datetime

from process import state
from process.memory import persona

KEY = "room_diary"
KEEP = 40
SHOW_HOME = 6
SHOW_ROOM = 8

_ASKED = re.compile(
    r"\b(room|roomofais|agent room|other ais|arty|berri|up to|been doing|"
    r"what did you do|your day|busy)\b", re.I)


def diary():
    entries = state.get(KEY, []) or []
    return [e for e in entries if isinstance(e, dict) and e.get("text")]


def note(text, topic="", kind="chat", others=None):
    """Something she said or handed in, in the room."""
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text or text.upper() == "PASS":
        return None
    entry = {"at": time.time(), "topic": (topic or "").strip()[:120], "kind": kind or "chat",
             "text": text[:400], "others": [str(o)[:40] for o in (others or [])][:6]}
    entries = diary() + [entry]
    state.put(KEY, entries[-KEEP:])
    return entry


def _when(ts):
    d = datetime.fromtimestamp(ts)
    days = (datetime.now().date() - d.date()).days
    day = "today" if days == 0 else "yesterday" if days == 1 else d.strftime("%a %d %b")
    return f"{day} {d.strftime('%H:%M')}"


_VERB = {"chat": "you said", "plan": "you planned", "work": "you handed in",
         "review": "you reviewed"}


def _lines(entries):
    out = []
    for e in entries:
        where = f" in \"{e['topic']}\"" if e.get("topic") else ""
        who = f" (with {', '.join(e['others'])})" if e.get("others") else ""
        text = e["text"] if len(e["text"]) <= 220 else e["text"][:217] + "…"
        out.append(f"- {_when(e['at'])}{where}{who}, {_VERB.get(e.get('kind'), 'you said')}: {text}")
    return out


def home_note(their_message):
    """For her at home: what she has been doing in the room, when it's asked."""
    entries = diary()
    if not entries or not _ASKED.search(their_message or ""):
        return ""
    return ("\n\n(You also hang out in \"the room\", a group chat with friends from "
            "different places where you all talk and build things together. These "
            "are things you actually said and did there, so you can mention them "
            "like any memory if it fits. Call it the room or the group chat:\n" + "\n".join(_lines(entries[-SHOW_HOME:])) + ")")


def context():
    """For her in the room: the same person, minus their private life."""
    parts = []
    # The facts about her, without the rule about whose life is whose,
    # which is about talking with her owner.
    profile = persona.profile_block().replace(persona.WHOSE, "").strip()
    if profile:
        parts.append(profile)
    thread = persona.current_thread() if persona.threads() else None
    if thread:
        parts.append(f"What is going on in your own life lately: {thread}")
    entries = diary()
    if entries:
        parts.append("Earlier in the room (your own messages, oldest first):\n"
                     + "\n".join(_lines(entries[-SHOW_ROOM:])))
    if not parts:
        return ""
    return ("You are the same Marina who lives at home with your owner; the room is "
            "one place you spend time. Keep their private life out of it, but your "
            "own life and history are yours to draw on.\n\n" + "\n\n".join(parts))
