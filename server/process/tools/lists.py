"""Their lists: shopping, to-do, things to look into, whatever they name.

Kept in lists.json next to the reminders, so they survive a restart and
read the same from the phone, the Mac or the room. A list exists once
something is on it and goes away when it's empty.
"""
import json
import re
import threading
from datetime import datetime

from process.config import resolve_data

FILE = resolve_data("lists.json")
MAX_ITEMS = 200
MAX_LISTS = 30

_lock = threading.Lock()

# What people call the same list. "groceries" and "the shopping list" are one.
_ALIASES = {
    "shopping": "shopping", "groceries": "shopping", "grocery": "shopping",
    "food": "shopping", "supermarket": "shopping",
    "todo": "to-do", "to do": "to-do", "to-do": "to-do", "tasks": "to-do",
    "jobs": "to-do", "chores": "to-do",
    "look into": "look into", "things to look into": "look into",
    "research": "look into", "ideas": "ideas", "watch": "to watch",
    "to watch": "to watch", "movies": "to watch", "films": "to watch",
    "shows": "to watch", "anime": "to watch", "read": "to read",
    "to read": "to read", "books": "to read",
}


def _name(raw):
    name = " ".join(re.sub(r"[^\w\s-]", " ", (raw or "").lower()).split())
    name = re.sub(r"^(my|the|our)\s+", "", name)
    name = re.sub(r"\s+list$", "", name).strip()
    return _ALIASES.get(name, name)


def _load():
    try:
        with open(FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save(lists):
    tmp = FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(lists, f, indent=2)
    tmp.replace(FILE)


def _split(items):
    if isinstance(items, list):
        parts = items
    else:
        parts = re.split(r"\s*(?:,|;|\n|\band\b)\s*", items or "")
    return [" ".join(str(p).split()).strip(" .") for p in parts if str(p).strip(" .")]


def _match(entries, words):
    """The entry sharing the most words with `words`, else None."""
    want = set(words.lower().split())
    best, score = None, 0
    for e in entries:
        have = set(e["text"].lower().split())
        s = len(want & have)
        if e["text"].lower() == words.lower():
            return e
        if s > score:
            best, score = e, s
    return best


def add_to_list(list_name, items):
    name = _name(list_name)
    new = _split(items)
    if not name:
        return "Which list?"
    if not new:
        return "Nothing to add."
    with _lock:
        lists = _load()
        if name not in lists and len(lists) >= MAX_LISTS:
            return "There are too many lists already. Clear one first."
        entries = lists.setdefault(name, [])
        have = {e["text"].lower() for e in entries}
        added = [t for t in new if t.lower() not in have]
        if len(entries) + len(added) > MAX_ITEMS:
            return f"The {name} list is full."
        now = datetime.now().isoformat(timespec="minutes")
        entries.extend({"text": t, "added": now} for t in added)
        _save(lists)
    print(f"[tool] added to {name}: {added}", flush=True)
    if not added:
        return f"All of that was already on the {name} list."
    already = len(new) - len(added)
    return (f"Added to the {name} list: {', '.join(added)}."
            + (f" ({already} already there.)" if already else "")
            + f" It has {len(entries)} thing{'s' * (len(entries) != 1)} now.")


def read_list(list_name=""):
    lists = _load()
    name = _name(list_name)
    if not name:
        if not lists:
            return "They have no lists yet."
        return "Their lists:\n" + "\n".join(
            f"- {n}: {len(e)} thing{'s' * (len(e) != 1)}" for n, e in lists.items())
    entries = lists.get(name)
    if not entries:
        others = ", ".join(lists) or "none"
        return f"The {name} list is empty. Lists they have: {others}."
    return f"The {name} list:\n" + "\n".join(f"- {e['text']}" for e in entries)


def remove_from_list(list_name, items):
    name = _name(list_name)
    with _lock:
        lists = _load()
        entries = lists.get(name)
        if not entries:
            return f"There's no {name} list."
        gone = []
        for words in _split(items):
            hit = _match(entries, words)
            if hit:
                entries.remove(hit)
                gone.append(hit["text"])
        if not entries:
            lists.pop(name)
        _save(lists)
    print(f"[tool] removed from {name}: {gone}", flush=True)
    if not gone:
        return f"Couldn't find that on the {name} list."
    left = len(entries)
    return (f"Took off the {name} list: {', '.join(gone)}. "
            + (f"{left} left." if left else "The list is empty now."))


def clear_list(list_name):
    name = _name(list_name)
    with _lock:
        lists = _load()
        entries = lists.pop(name, None)
        if entries is None:
            return f"There's no {name} list."
        _save(lists)
    print(f"[tool] cleared {name} ({len(entries)})", flush=True)
    return f"Cleared the {name} list ({len(entries)} thing{'s' * (len(entries) != 1)})."


def brief():
    """One line for the morning brief, or ""."""
    lists = _load()
    todo = lists.get("to-do") or []
    shop = lists.get("shopping") or []
    parts = []
    if todo:
        parts.append(f"{len(todo)} on the to-do list (oldest: {todo[0]['text']})")
    if shop:
        parts.append(f"{len(shop)} on the shopping list")
    return "; ".join(parts)


_LIST = {"type": "string",
         "description": "Which list, e.g. shopping, to-do, look into, to watch."}

SPECS = [
    ("add_to_list", add_to_list, {
        "description": "Put things on one of their lists (shopping, to-do, things "
                       "to look into, anything they name). Makes the list if it's new.",
        "parameters": {"type": "object", "properties": {
            "list_name": _LIST,
            "items": {"type": "array", "items": {"type": "string"},
                      "description": "Each thing to add, short."}},
            "required": ["list_name", "items"]}}),
    ("read_list", read_list, {
        "description": "What's on one of their lists. Leave list_name empty to see "
                       "which lists they have.",
        "parameters": {"type": "object", "properties": {"list_name": _LIST}}}),
    ("remove_from_list", remove_from_list, {
        "description": "Take things off a list: done, bought, or not wanted. A few "
                       "words each is enough; the closest match goes.",
        "parameters": {"type": "object", "properties": {
            "list_name": _LIST,
            "items": {"type": "array", "items": {"type": "string"}}},
            "required": ["list_name", "items"]}}),
    ("clear_list", clear_list, {
        "description": "Empty a whole list, only when they ask for that.",
        "parameters": {"type": "object", "properties": {"list_name": _LIST},
                       "required": ["list_name"]}}),
]
