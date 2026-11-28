"""Long-term memory, kept in memory.json.

Three kinds of thing live here, told apart by `source`:

  facts     what is true of them ("The user has a cat"). All of them go
            into the system prompt; there are few enough.
  events    something with a day attached ("The user presents on Friday"),
            kept until she has asked how it went. See process.memory.followup.
  episodes  a few sentences on a stretch of conversation that has scrolled
            out of her window, so what happened isn't lost with it.
"""
import json
import re
import threading
import time
import uuid
from datetime import date, datetime, timezone

from process import shared
from process import state
from process.config import resolve_data

MEMORY_FILE = resolve_data("memory.json")

MAX_FACTS = 60

EVENT = "event"        # a dated thing to ask about afterwards; has `due`
EPISODE = "episode"    # what a stretch of conversation was about
MAX_EVENTS = 20
MAX_SELF = 40          # notes about herself; the oldest make way
MAX_EPISODES = 40
EPISODES_IN_PROMPT = 5
# Only what she picked up by herself makes way when memory is full. What
# they told her to remember, or wrote in by hand, stays.
_EVICTABLE = {"auto"}

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


def local_facts():
    return load()["facts"]


def all_facts():
    """Every fact, from the shared home if there is one."""
    if shared.enabled():
        facts = shared.call("GET", "/shared/memory")
        if isinstance(facts, list):
            with _lock:
                save({"facts": facts})  # the copy used if the home is down
            return facts
    return local_facts()


_INSTRUCTION = re.compile(
    r"^(say|tell|ask|remind|greet|send|open|play|show|give|make sure|"
    r"remember to|don'?t forget|note that|be sure|let|call)\b", re.I)
_EPHEMERAL = re.compile(
    r"\b(currently|right now|at the moment|just now|is talking to|"
    r"is chatting|today|this (morning|afternoon|evening|session))\b", re.I)
_SELF = re.compile(r"^(i|i'?m|i'?ve|marina|my|we|us|our)\b", re.I)


def _is_durable_fact(text):
    """Reject instructions, passing state, questions and the model talking
    about itself."""
    t = text.strip()
    if len(t) < 8 or len(t) > 200:
        return False
    if t[0] in "(\"'" or t[-1] in "!?":
        return False
    if _INSTRUCTION.match(t):
        return False
    if _EPHEMERAL.search(t):
        return False
    if _SELF.match(t):
        return False
    return True


def add(text, source="auto", due=None):
    """Store a fact, in the shared home if there is one. Returns the fact,
    or None if it duplicates an existing one. `due` is the day of an event,
    as YYYY-MM-DD."""
    if state.rehearsing():
        return None
    if shared.enabled():
        body = {"text": text, "source": source}
        if due:
            body["due"] = due
        out = shared.call("POST", "/shared/memory", body)
        if isinstance(out, dict):
            return out.get("fact")
    return local_add(text, source, due)


SELF = "self"  # the source of notes she keeps about herself
MAX_SELF_IN_PROMPT = 20
JOKE = "joke"  # running jokes and nicknames the two of them share
MAX_JOKES = 20


def _is_self_note(text):
    t = text.strip()
    return 8 <= len(t) <= 200 and t[-1] != "?"


def _kind(fact):
    source = fact.get("source")
    return source if source in (EVENT, EPISODE) else "fact"


def _acceptable(text, source):
    if source == EPISODE:
        return 20 <= len(text) <= 600
    if source == EVENT:
        return 8 <= len(text) <= 200 and text[-1] != "?"
    if source in (SELF, JOKE):
        return _is_self_note(text)
    return _is_durable_fact(text)


def _trim(facts):
    """Keep each kind within its limit. Events and episodes go oldest first;
    facts lose the least mentioned of what she picked up by herself."""
    out = []
    for kind, limit in ((EVENT, MAX_EVENTS), (EPISODE, MAX_EPISODES)):
        mine = [f for f in facts if _kind(f) == kind]
        out += sorted(mine, key=lambda f: f.get("created", ""))[-limit:]
    hers = [f for f in facts if f.get("source") == "self"]
    out += sorted(hers, key=lambda f: f.get("created", ""))[-MAX_SELF:]
    ours = [f for f in facts if f.get("source") == JOKE]
    out += sorted(ours, key=lambda f: f.get("created", ""))[-MAX_JOKES:]
    plain = [f for f in facts if _kind(f) == "fact" and f.get("source") not in ("self", JOKE)]
    over = len(plain) - MAX_FACTS
    if over > 0:
        loose = sorted((f for f in plain if f.get("source") in _EVICTABLE),
                       key=lambda f: (f.get("mentions", 1), f.get("updated", "")))
        drop = {id(f) for f in loose[:over]}
        plain = [f for f in plain if id(f) not in drop]
        # Nothing left that may go: the oldest of the rest, as before.
        plain = plain[-MAX_FACTS:]
    keep = {id(f) for f in out + plain}
    return [f for f in facts if id(f) in keep]


def local_add(text, source="auto", due=None):
    text = " ".join((text or "").split())
    if not _acceptable(text, source):
        return None

    with _lock:
        data = load()
        for existing in data["facts"]:
            if source == EPISODE or _kind(existing) != _kind({"source": source}):
                continue
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
        if due:
            fact["due"] = str(due)
        data["facts"].append(fact)
        data["facts"] = _trim(data["facts"])
        save(data)
        return fact


def events():
    return [f for f in all_facts() if f.get("source") == EVENT and f.get("due")]


def episodes():
    found = [f for f in all_facts() if f.get("source") == EPISODE]
    return sorted(found, key=lambda f: f.get("created", ""))


def pin(fact_id):
    """Keep a fact for good: it becomes something they told her, which is
    never pushed out to make room."""
    if shared.enabled():
        out = shared.call("POST", f"/shared/memory/{fact_id}/pin")
        if isinstance(out, dict):
            return bool(out.get("ok"))
    return local_pin(fact_id)


def local_pin(fact_id):
    with _lock:
        data = load()
        for f in data["facts"]:
            if f["id"] == fact_id and f.get("source") in _EVICTABLE:
                f["source"] = "told"
                save(data)
                return True
    return False


last_removed = 0.0     # time.time() of the last fact removed, any way


def remove(fact_id):
    global last_removed
    if state.rehearsing():
        return False
    last_removed = time.time()
    if shared.enabled():
        out = shared.call("DELETE", f"/shared/memory/{fact_id}")
        if isinstance(out, dict):
            return bool(out.get("ok"))
    return local_remove(fact_id)


def local_remove(fact_id):
    with _lock:
        data = load()
        before = len(data["facts"])
        data["facts"] = [f for f in data["facts"] if f["id"] != fact_id]
        save(data)
        return len(data["facts"]) < before


def find(description, min_score=0.3):
    """The remembered fact or note that best matches `description`, or None."""
    want = " ".join((description or "").lower().split())
    if not want:
        return None
    best, score = None, 0.0
    for f in all_facts():
        if f.get("source") == EPISODE:
            continue
        text = f["text"].lower()
        s = 1.0 if want in text else _similar(f["text"], description)
        if s > score:
            best, score = f, s
    return best if score >= min_score else None


def clear():
    if shared.enabled():
        shared.call("DELETE", "/shared/memory")
    local_clear()


def local_clear():
    with _lock:
        save({"facts": []})


_MONTHS = ("january february march april may june july august september october "
           "november december").split()
_DAY_MONTH = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?(?:\s+of)?\s+(" + "|".join(_MONTHS) + r")\b"
    r"|\b(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
_ANNUAL = re.compile(r"birthday|anniversary|\bborn\b", re.I)


def _yearly_date(text):
    """(month, day) of a birthday or anniversary fact, else None."""
    if not _ANNUAL.search(text):
        return None
    m = _DAY_MONTH.search(text)
    if not m:
        return None
    day, month = (m.group(1), m.group(2)) if m.group(1) else (m.group(4), m.group(3))
    return _MONTHS.index(month.lower()) + 1, int(day)


def _for_today(facts, today):
    """Birthdays and anniversaries only on the day itself: the rest of the
    year she'd bring them up anyway ("happy belated birthday week")."""
    out = []
    for f in facts:
        when = _yearly_date(f["text"])
        if when is None:
            out.append(f)
        elif when == (today.month, today.day):
            out.append({**f, "text": f["text"] + " (that's today)"})
    return out


def _when(fact):
    """"12 November: " for an episode, from when it was saved."""
    try:
        d = datetime.fromisoformat(fact.get("created", "")).astimezone()
    except ValueError:
        return ""
    return f"{d.day} {d:%B}: "


def as_prompt_block(today=None):
    everything = all_facts()
    facts = _for_today([f for f in everything
                        if f.get("source") not in (SELF, EVENT, EPISODE)],
                       today or date.today())
    mine = [f for f in everything if f.get("source") == SELF]
    jokes = [f for f in everything if f.get("source") == JOKE]
    told = [f for f in everything if f.get("source") == EPISODE]
    out = ""
    if facts:
        # In the order she learned them, so hearing one again doesn't
        # reshuffle the list: this text sits in the cached part of the
        # prompt, and any change to it makes the server reread everything
        # after it.
        facts = sorted(facts, key=lambda f: f.get("created", ""))
        lines = "\n".join(f"- {f['text']}" for f in facts)
        out += (
            "\n\nYou remember these things about the user from earlier "
            "conversations. They are about them, not you: \"the user\" is the "
            "person you are talking to. Use them only when genuinely relevant, "
            "never recite them back, and never open a reply with the user's "
            "name.\n"
            f"{lines}"
        )
    if told:
        told = sorted(told, key=lambda f: f.get("created", ""))[-EPISODES_IN_PROMPT:]
        lines = "\n".join(f"- {_when(f)}{f['text']}" for f in told)
        out += (
            "\n\nWhat the two of you talked about before the messages below, "
            "oldest first. It happened; you can call back to it like anyone "
            "would, without retelling it.\n"
            f"{lines}"
        )
    if mine:
        mine = sorted(mine, key=lambda f: f.get("created", ""))[-MAX_SELF_IN_PROMPT:]
        lines = "\n".join(f"- {f['text']}" for f in mine)
        out += (
            "\n\nNotes you've kept about yourself: your own opinions, tastes and "
            "what you've been up to. They're yours, so stay true to them, but "
            "don't announce them.\n"
            f"{lines}"
        )
    if jokes:
        jokes = sorted(jokes, key=lambda f: f.get("created", ""))[-MAX_JOKES:]
        lines = "\n".join(f"- {f['text']}" for f in jokes)
        out += (
            "\n\nRunning jokes and names between the two of you. Bring one back "
            "now and then when it fits, the way friends do, without explaining it.\n"
            f"{lines}"
        )
    return out
