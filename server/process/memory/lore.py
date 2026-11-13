"""Memories that come up when their subject does.

The facts in memory.json all go into every prompt, which is fine for "the
user uses Kubuntu" but wrong for a story: a shared memory sitting in front of
her on every turn gets retold every few turns. Lore entries are the stories.
Each one has trigger words, and only when one of them appears in the last few
messages (theirs or hers) does the entry go in front of her, for that reply.

An entry, in lore.json next to her memory:

    {"keys": ["hack club", "/hackclub/"],   # words or /regex/, case-insensitive
     "text": "You came back from the meeting ...",
     "cooldown": 12,      # replies before it can come up again (default 8)
     "sticky": 2,         # replies it stays in front of her once triggered (default 1)
     "probability": 1.0,  # chance it comes up when triggered (default 1)
     "constant": false,   # always in front of her, no keys needed
     "priority": 0}       # higher wins when more trigger than fit

Like the clock and the repetition note, triggered lore goes on the newest
message, never into the system prompt, so the server's cached prefix stays
the same from turn to turn.
"""
import json
import random
import re
import threading

from process.config import resolve_data, setting

DEFAULT_COOLDOWN = 8
DEFAULT_STICKY = 1

_lock = threading.Lock()
_turn = 0          # replies so far this run; cooldowns count in these
_last = {}         # entry key -> turn it last came up
_sticky = {}       # entry key -> turns it stays in front of her
_cache = {"mtime": None, "entries": []}


def enabled():
    return bool(setting("lore", "enabled", True)) and bool(setting("llm", "recall", True))


def _path():
    return resolve_data(setting("lore", "file", "lore.json"))


def _compile(key):
    key = str(key).strip()
    if len(key) > 2 and key.startswith("/") and key.endswith("/"):
        try:
            return re.compile(key[1:-1], re.I)
        except re.error:
            return None
    if not key:
        return None
    # Whole words, so "art" doesn't fire on "start"; inner spaces match any gap.
    body = r"\s+".join(re.escape(w) for w in key.split())
    return re.compile(rf"(?<![\w']){body}(?![\w'])", re.I)


def _normalise(raw):
    out = []
    for i, e in enumerate(raw if isinstance(raw, list) else []):
        if not isinstance(e, dict) or not str(e.get("text", "")).strip():
            continue
        keys = e.get("keys") or []
        if isinstance(keys, str):
            keys = [k for k in keys.split(",")]
        pats = [p for p in (_compile(k) for k in keys) if p]
        constant = bool(e.get("constant", False))
        if not pats and not constant:
            continue
        out.append({
            "id": str(e.get("id") or i),
            "text": str(e["text"]).strip(),
            "patterns": pats,
            "constant": constant,
            "cooldown": max(0, int(e.get("cooldown", DEFAULT_COOLDOWN))),
            "sticky": max(1, int(e.get("sticky", DEFAULT_STICKY))),
            "probability": min(1.0, max(0.0, float(e.get("probability", 1.0)))),
            "priority": int(e.get("priority", 0)),
        })
    return out


def entries():
    """The entries in lore.json, re-read whenever the file changes."""
    path = _path()
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    with _lock:
        if _cache["mtime"] != mtime:
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                print(f"[lore] couldn't read {path}: {e}", flush=True)
                raw = []
            _cache["entries"] = _normalise(raw.get("entries", raw) if isinstance(raw, dict) else raw)
            _cache["mtime"] = mtime
        return list(_cache["entries"])


def _text(m):
    c = m.get("content") if isinstance(m, dict) else m
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


def _scan_text(history, their_message):
    depth = int(setting("lore", "scan_depth", 4))
    recent = [m for m in history if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    parts = [_text(m) for m in recent[-depth:]] if depth > 0 else []
    if their_message:
        parts.append(_text(their_message))
    return "\n".join(parts)


def triggered(history, their_message="", roll=random.random):
    """Entries to put in front of her for this reply, and advance the clock.
    Call once per reply."""
    global _turn
    pool = entries()
    if not pool:
        return []
    text = _scan_text(history, their_message)
    limit = int(setting("lore", "max_entries", 3))
    with _lock:
        _turn += 1
        now = _turn
        picked = []
        for e in pool:
            k = e["id"] + "\x00" + e["text"][:40]
            if e["constant"]:
                picked.append(e)
                continue
            if _sticky.get(k, 0) > 0:          # still in front of her from before
                _sticky[k] -= 1
                picked.append(e)
                continue
            last = _last.get(k)
            if last is not None and now - last <= e["cooldown"]:
                continue
            if not any(p.search(text) for p in e["patterns"]):
                continue
            if roll() > e["probability"]:
                continue
            _last[k] = now
            _sticky[k] = e["sticky"] - 1
            picked.append(e)
        picked.sort(key=lambda e: (not e["constant"], -e["priority"]))
        return picked[:limit] if limit > 0 else picked


def note(history, their_message=""):
    """The note for her newest message, or "" if nothing came up."""
    if not enabled():
        return ""
    found = triggered(history, their_message)
    if not found:
        return ""
    body = " ".join(e["text"] for e in found)
    return ("\n\n(Note to you, not from them: this has come up, and you remember it: "
            + body
            + " Use it only if it fits, the way a friend would, in your own words. "
              "Don't recite it or explain how you know.)")


def reset():
    """Forget cooldowns, for tests and when the conversation is cleared."""
    global _turn
    with _lock:
        _turn = 0
        _last.clear()
        _sticky.clear()
        _cache["mtime"] = None
