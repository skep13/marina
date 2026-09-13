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

MAX_FACTS = 60

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
    tmp.replace(MEMORY_FILE)


def all_facts():
    return load()["facts"]


import re as _re

# A durable fact is a plain statement about the user that stays true. These
# patterns catch what the model kept storing instead: things it was told to do,
# passing state that is only true this second, and its own narration of itself.
_INSTRUCTION = _re.compile(
    r"^(say|tell|ask|remind|greet|send|open|play|show|give|make sure|"
    r"remember to|don'?t forget|note that|be sure|let|call)\b", _re.I)
_EPHEMERAL = _re.compile(
    r"\b(currently|right now|at the moment|just now|is talking to|"
    r"is chatting|today|this (morning|afternoon|evening|session))\b", _re.I)
# First word signalling the "fact" is about Marina or a third party, not the user.
_SELF = _re.compile(r"^(i|i'?m|i'?ve|marina|my|we|us|our)\b", _re.I)


def _is_durable_fact(text):
    """True if this is worth keeping as a lasting fact about the user."""
    t = text.strip()
    if len(t) < 8 or len(t) > 200:
        return False
    if t[0] in "(\"'" or t[-1] in "!?":       # parenthetical dumps, chatter, questions
        return False
    if _INSTRUCTION.match(t):
        return False
    if _EPHEMERAL.search(t):
        return False
    if _SELF.match(t):
        return False
    return True


def add(text, source="auto"):
    """Store a fact. Returns the fact, or None if it duplicates an existing one."""
    text = " ".join((text or "").split())
    if not _is_durable_fact(text):
        return None

    with _lock:
        data = load()
        for existing in data["facts"]:
            if _similar(existing["text"], text) >= DEDUPE_THRESHOLD:
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
    return (
        "\n\nYou remember these things about the user from earlier "
        "conversations. Use them only when genuinely relevant, never recite "
        "them back, and never open a reply with the user's name.\n"
        f"{lines}"
    )
