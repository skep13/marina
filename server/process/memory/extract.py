"""Pull facts about the user out of each exchange, on a background thread."""
import json
import re
import threading
import time
from datetime import date, datetime, timedelta

from process import backend
from process.memory import store

PROMPT = """Extract durable facts the USER stated about themselves.

RECORD when the user states something about themselves that stays true:
hardware they own, projects they are building, where they live or work, what
they prefer to be called, ongoing constraints.

DO NOT RECORD:
- anything you inferred rather than heard. If they did not say it, it does
  not go in. Never guess name, gender, age, location or job.
- anything about you, the assistant, or anything from your own reply
- passing context: questions, requests, opinions, greetings, thanks
- file names, model names or app names treated as personal details

Write each fact as one short sentence starting with "The user". Turn
relative dates into real ones using today's date, so "my birthday was
yesterday" is stored as the actual day, never as "yesterday".

ALSO RECORD anything coming up on a particular day that a friend would ask
about afterwards: an exam, a presentation, an interview, a trip, an
appointment, a deadline, a match. Write those as an object instead of a
string, with the day worked out from today's date:
{"event": "The user has their driving test", "on": "2026-10-13"}
When they gave a day ("tomorrow", "on Friday", "the 3rd"), use it. When it
is clearly coming up but the day is loose ("next week", "in a few days",
"coming up"), give your best guess and add "rough": true. "Someday" or
"next year" is too vague; leave it out. Things already over are not events.

ALSO, from YOUR OWN reply only: if you (Marina) said something new and
concrete about your own life, tastes or opinions that you would need to
stay consistent with later, record it as {"self": "You ..."}. Not moods,
not reactions to them, nothing about them.

ALSO: if the two of you just made a joke, nickname or bit that could become
a running joke (a silly name for something, a phrase you both latched onto,
a teasing callback), record it as {"joke": "..."}, describing it so it makes
sense later. Only real shared bits, not every pun.

ALSO: if the user sounds genuinely low, struggling or hopeless in this
message, even quietly, add {"feeling": "low"}; if they talk about not
wanting to be alive or hurting themselves, {"feeling": "crisis"}. Not for
jokes, ordinary complaining or being tired after a long day.

Reply with ONLY a JSON array. No prose, no markdown, no fences.

user: "my beelink has 32 gigs of ram"
["The user has a Beelink with 32 GB of RAM"]

user: "i'm building a vtuber assistant"
["The user is building a VTuber assistant"]

user: "it was my birthday yesterday" (today is Monday 12 October 2026)
["The user's birthday is on 11 October"]

user: "ugh my driving test is tomorrow" (today is Monday 12 October 2026)
[{"event": "The user has their driving test", "on": "2026-10-13"}]

user: "got an interview next week, kind of dreading it" (today is Monday 12 October 2026)
[{"event": "The user has an interview", "on": "2026-10-19", "rough": true}]

user: "what are you watching" / you replied: "rewatching Mob Psycho, season two is the best one"
[{"self": "You think season two of Mob Psycho is the best one"}]

user: "my laptop is basically a space heater at this point" / you replied: "the space heater lives. long live the space heater"
[{"joke": "You both call the user's overheating laptop 'the space heater'"}]

user: "i don't really see the point of any of it lately"
[{"feeling": "low"}]

user: "call me Sam"
["The user prefers to be called Sam"]

user: "what's the weather like"
[]

user: "thanks, that works"
[]"""

MAX_PER_TURN = 4
MAX_FACT_CHARS = 160

MIN_USER_CHARS = 15

_TRIVIAL = {
    "hi", "hey", "hello", "yo", "sup", "thanks", "thank you", "ok", "okay",
    "yes", "no", "yeah", "nah", "cool", "nice", "lol", "bye", "goodnight",
    "good morning", "what", "huh", "why", "how", "sure", "please", "stop",
}


def worth_extracting(user_text):
    text = (user_text or "").strip().lower().rstrip("?!.,")
    if len(text) < MIN_USER_CHARS:
        return False
    if text in _TRIVIAL:
        return False
    return True


def _parse(raw, today=None):
    if not raw:
        return []
    text = raw.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()

    match = re.search(r"\[.*\]", text, re.S)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []

    out = []
    for item in parsed:
        if isinstance(item, dict):
            found = _event(item, today) or _self(item) or _joke(item) or _feeling(item)
            if found:
                out.append(found)
            continue
        if not isinstance(item, str):
            continue
        item = " ".join(item.split())
        if 4 <= len(item) <= MAX_FACT_CHARS:
            out.append(item)
    return out[:MAX_PER_TURN]


def _self(item):
    text = item.get("self")
    if not isinstance(text, str):
        return None
    text = " ".join(text.split())
    if 8 <= len(text) <= MAX_FACT_CHARS and text.lower().startswith("you "):
        return {"self": text}
    return None


def _joke(item):
    text = item.get("joke")
    if not isinstance(text, str):
        return None
    text = " ".join(text.split())
    return {"joke": text} if 8 <= len(text) <= MAX_FACT_CHARS else None


def _feeling(item):
    how = item.get("feeling")
    return {"feeling": how} if how in ("low", "crisis") else None


EVENT_HORIZON = 120   # days ahead; further off than this is a wrong date


def _event(item, today=None):
    """{"event", "on"} if this is a dated thing still to come, else None."""
    text, on = item.get("event"), item.get("on")
    if not isinstance(text, str) or not isinstance(on, str):
        return None
    text = " ".join(text.split())
    try:
        day = date.fromisoformat(on.strip()[:10])
    except ValueError:
        return None
    today = today or date.today()
    if not (today <= day <= today + timedelta(days=EVENT_HORIZON)):
        return None
    if not 8 <= len(text) <= MAX_FACT_CHARS:
        return None
    return {"event": text, "on": day.isoformat() + ("~" if item.get("rough") is True else "")}


def extract(client, model, user_text, assistant_text):
    try:
        from process.llm_funcs.llm_scr import chat_completion
        completion = chat_completion(
            messages=[
                {"role": "system", "content": PROMPT},
                {"role": "user",
                 "content": f"TODAY IS {datetime.now():%A %-d %B %Y}.\n\n"
                            f"USER SAID: {user_text}\n\nYOU REPLIED: {assistant_text}"},
            ],
            temperature=0,
            max_tokens=200,
            stream=False,
        )
        if backend.on_fallback():
            # The small backup model invents facts; better to learn nothing.
            return []
        return _parse(completion.choices[0].message.content)
    except Exception as e:
        print(f"[memory] extraction failed: {type(e).__name__}: {e}", flush=True)
        return []


_EXPLICIT = [
    re.compile(r"\b(?:please\s+)?remember\s*[:,]?\s*(?:that\s+|this\s*[:,]?\s*)?(.+)", re.I),
    re.compile(r"\bdon'?t\s+forget\s*[:,]?\s*(?:that\s+)?(.+)", re.I),
    re.compile(r"\bmake\s+a\s+note\s*[:,]?\s*(?:that\s+|of\s+)?(.+)", re.I),
    re.compile(r"\bkeep\s+in\s+mind\s*[:,]?\s*(?:that\s+)?(.+)", re.I),
]

# "forget that I live in Cardiff", "please forget about my exam", "I moved,
# forget that". Only at the start of a sentence or clause, so "don't forget",
# "I always forget my keys" and "nvm forget it" don't count.
_FORGET = re.compile(
    r"(?:^|[.!?,;]\s*)(?:(?:please|pls|plz|can\s+you|could\s+you|you\s+can)\s+)?"
    r"forget\s*[:,]?\s*(?:that\s+|about\s+)?(.+)", re.I)
_VAGUE = {"that", "this", "it", "about it", "about that", "everything", "what i said"}

_IRREGULAR = {"have": "has", "am": "is", "'m": "is", "do": "does", "go": "goes"}
_VERBS = {
    "live", "work", "prefer", "use", "own", "need", "want", "run", "like",
    "hate", "have", "build", "study", "play", "speak", "drive", "code",
    "stream", "sleep", "eat", "am", "do", "go",
}
_ADVERBS = {"only", "just", "also", "currently", "usually", "always", "never",
            "sometimes", "still", "mainly", "mostly", "often", "really"}


def _conjugate(word):
    w = word.lower()
    if w in _IRREGULAR:
        return _IRREGULAR[w]
    if w.endswith(("s", "x", "z", "ch", "sh")):
        return w + "es"
    if w.endswith("y") and len(w) > 1 and w[-2] not in "aeiou":
        return w[:-1] + "ies"
    return w + "s"


def _to_third_person(fact):
    """"I live in Leeds" -> "The user lives in Leeds"."""
    fact = re.sub(r"^i\s+am\b", "the user is", fact, flags=re.I)
    fact = re.sub(r"^i'?m\b", "the user is", fact, flags=re.I)
    fact = re.sub(r"^my\b", "the user's", fact, flags=re.I)
    fact = re.sub(r"^me\b", "the user", fact, flags=re.I)
    fact = re.sub(r"^i\s+", "the user ", fact, flags=re.I)

    parts = fact.split()
    if len(parts) >= 3 and parts[0].lower() == "the" and parts[1].lower() == "user":
        i = 2
        while i < len(parts) and parts[i].lower() in _ADVERBS:
            i += 1
        if i < len(parts) and parts[i].lower() in _VERBS:
            parts[i] = _conjugate(parts[i])
            fact = " ".join(parts)
    return fact


def explicit_fact(user_text):
    """The fact from "remember that ...", or None."""
    text = " ".join((user_text or "").split())
    for pattern in _EXPLICIT:
        m = pattern.search(text)
        if not m:
            continue
        fact = m.group(1).strip(" .!?,")
        # "i switched to arch, remember that": the fact comes before it.
        if fact.lower() in ("that", "this", "it"):
            fact = re.sub(r"^(?:oh\s+)?(?:btw|by the way|also|and|so|anyway)\b[\s,]*", "",
                          text[:m.start()].strip(" .!?,"), flags=re.I)
        if len(fact) < 3:
            continue
        fact = _to_third_person(fact)
        return fact[0].upper() + fact[1:]
    return None


def explicit_forget(user_text):
    """What to forget from "forget that ...", or None. "I moved, forget that"
    points back at the words before it."""
    text = " ".join((user_text or "").split())
    m = _FORGET.search(text)
    if not m:
        return None
    what = re.split(r"[,;]|\s+(?:because|cos|cause|since|as)\s+", m.group(1))[0].strip(" .!?")
    if what.lower() in ("it", "about it", "everything", "what i said"):
        return None                        # "forget it" = never mind
    if what.lower() in _VAGUE:
        what = text[:m.start()].strip(" .!?,")
        what = re.sub(r"^(?:oh\s+)?(?:btw|by the way|also|and|so|anyway|actually)\b[\s,]*", "",
                      what, flags=re.I)
        if len(what.split()) < 2:          # "ugh, forget it"
            return None
    return what if len(what) >= 3 else None


def forget_explicit(user_text):
    """Drop the remembered fact they asked her to forget, whether or not she
    calls the forget tool. Returns the removed fact's text, or None."""
    what = explicit_forget(user_text)
    if not what:
        return None
    # She called the forget tool for it during this reply: done already, and
    # a second pass would take out the next-closest fact.
    if time.time() - store.last_removed < 120:
        return None
    found = store.find(what, min_score=0.5)
    if not found or not store.remove(found["id"]):
        print(f"[memory] asked to forget {what!r}, nothing close enough", flush=True)
        return None
    print(f"[memory] -{found['text']}", flush=True)
    return found["text"]


def remember_async(client, model, user_text, assistant_text):
    forget_explicit(user_text)
    direct = explicit_fact(user_text)
    if direct:
        fact = store.add(direct, source="explicit")
        print(f"[memory] +{direct}" if fact else f"[memory] (already knew) {direct}", flush=True)
        return

    if not worth_extracting(user_text):
        return

    def work():
        for item in extract(client, model, user_text, assistant_text):
            if isinstance(item, dict) and "feeling" in item:
                from process import care
                care.heard(item["feeling"])
                continue
            if isinstance(item, dict) and "joke" in item:
                if store.add(item["joke"], source=store.JOKE):
                    print(f"[memory] +{item['joke']} (running joke)", flush=True)
                continue
            if isinstance(item, dict) and "self" in item:
                if store.add(item["self"], source=store.SELF):
                    print(f"[memory] +{item['self']} (about herself)", flush=True)
                continue
            if isinstance(item, dict):
                fact = store.add(item["event"], source=store.EVENT, due=item["on"])
                if fact:
                    print(f"[memory] +{fact['text']} (on {item['on']})", flush=True)
                continue
            fact = store.add(item, source="auto")
            if fact:
                print(f"[memory] +{fact['text']}", flush=True)

    threading.Thread(target=work, daemon=True).start()
