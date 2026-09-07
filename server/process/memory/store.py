"""Long-term memory: durable facts that outlive the conversation.

The conversation history is short-term — it gets trimmed so the context window
stays bounded. Anything worth keeping past that gets distilled into a fact and
stored here, then injected into the system prompt on every turn.

Facts are plain text, one idea each, stored as JSON. No embeddings: at a few
dozen facts, sending all of them costs less than retrieving the right ones, and
it means the whole store is human-readable and hand-editable.
"""
import json
import re
import threading
import uuid
from datetime import datetime, timezone

from process.config import REPO_ROOT

MEMORY_FILE = REPO_ROOT / "memory.json"

# Beyond this, the oldest unreferenced facts get dropped. ~60 short facts is
# roughly 1,200 tokens — affordable on every turn, even for a small local model.
MAX_FACTS = 60

# Two facts sharing this proportion of their words are treated as the same fact.
DEDUPE_THRESHOLD = 0.7

_lock = threading.Lock()

_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "to", "of", "and", "or",
    "in", "on", "at", "for", "with", "his", "her", "their", "they", "user",
    "users", "he", "she", "it", "that", "this", "has", "have", "had", "be",
}


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tokens(text):
    # Strip possessives before splitting: without this "jacob's" and "jacob"
    # look like different words and near-identical facts both get stored.
    lowered = text.lower().replace("'s ", " ").replace("s' ", " ").replace("'", "")
    words = re.findall(r"[a-z0-9]+", lowered)
    return {w for w in words if w not in _STOPWORDS and len(w) > 2}


def _similar(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def load():
    if not MEMORY_FILE.exists():
        return {"facts": []}
    try:
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"facts": []}
    if not isinstance(data, dict) or not isinstance(data.get("facts"), list):
        return {"facts": []}
    return data


def save(data):
    tmp = MEMORY_FILE.with_suffix(".json.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp.replace(MEMORY_FILE)      # atomic, so a crash can't truncate the store


def all_facts():
    return load()["facts"]


def add(text, source="auto"):
    """Store a fact. Returns the fact, or None if it duplicates an existing one."""
    text = " ".join((text or "").split())
    if len(text) < 4:
        return None

    with _lock:
        data = load()
        for existing in data["facts"]:
            if _similar(existing["text"], text) >= DEDUPE_THRESHOLD:
                # Refresh the timestamp so repeated mentions keep it alive.
                existing["updated"] = _now()
                existing["mentions"] = existing.get("mentions", 1) + 1
                save(data)
                return None

        fact = {
            "id": uuid.uuid4().hex[:8],
            "text": text,
            "created": _now(),
            "updated": _now(),
            "mentions": 1,
            "source": source,
        }
        data["facts"].append(fact)

        # Evict the least-mentioned, oldest facts first.
        if len(data["facts"]) > MAX_FACTS:
            data["facts"].sort(key=lambda f: (f.get("mentions", 1), f.get("updated", "")))
            data["facts"] = data["facts"][-MAX_FACTS:]

        save(data)
        return fact


def remove(fact_id):
    with _lock:
        data = load()
        before = len(data["facts"])
        data["facts"] = [f for f in data["facts"] if f["id"] != fact_id]
        save(data)
        return len(data["facts"]) < before


def clear():
    with _lock:
        save({"facts": []})


def as_prompt_block():
    """The memory section injected into the system prompt, or '' if empty."""
    facts = all_facts()
    if not facts:
        return ""

    facts = sorted(facts, key=lambda f: f.get("updated", ""), reverse=True)
    lines = "\n".join(f"- {f['text']}" for f in facts)
    # Instruction first, then the list: a trailing instruction after a long
    # list is the part a small model is most likely to skim past.
    return (
        "\n\nYou remember these things about the user from earlier "
        "conversations. Use them only when genuinely relevant, never recite "
        "them back, and never open a reply with the user's name.\n"
        f"{lines}"
    )
