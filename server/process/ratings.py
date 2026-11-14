"""Thumbs up or down on her last reply.

Each rating is saved with the exchange it was about, one JSON object per
line in ratings.jsonl next to her memory. It changes nothing about how she
talks today; it is the record of which replies sounded like her and which
didn't, for picking examples and for training later.
"""
import json
import threading
from datetime import datetime

from process.config import resolve_data

_lock = threading.Lock()


def _path():
    return resolve_data("ratings.jsonl")


def last_exchange(history):
    """(what they said, what she said) for her latest reply."""
    her = them = None
    for m in reversed(history):
        if her is None and m.get("role") == "assistant":
            her = m.get("content")
        elif her is not None and m.get("role") == "user":
            them = m.get("content")
            break
    return them, her


def rate(good, history, model="", note=""):
    """Save a rating of her latest reply. Returns it, or None with no reply."""
    them, her = last_exchange(history)
    if not her:
        return None
    entry = {"at": datetime.now().astimezone().isoformat(timespec="seconds"),
             "good": bool(good), "them": them, "her": her, "model": model}
    if note:
        entry["note"] = str(note)[:500]
    with _lock:
        with open(_path(), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def counts():
    good = bad = 0
    try:
        with open(_path(), encoding="utf-8") as f:
            for line in f:
                try:
                    if json.loads(line).get("good"):
                        good += 1
                    else:
                        bad += 1
                except ValueError:
                    continue
    except OSError:
        pass
    return {"good": good, "bad": bad}
