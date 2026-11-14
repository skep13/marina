"""Bringing back an older stretch of conversation when its subject returns.

Only her latest few episodes sit in her prompt (see process.memory.store).
The older ones are looked through for each message, and the one that best
matches what they just said rides on her newest message for that reply.

Matching is by shared words unless `recall.embed_model` names an embedding
model on her server, in which case it is by meaning. That is off by default
on purpose: on a server that holds one model at a time, asking for the
embedding model would push her own model out of memory.
"""
import json
import math
import re
import threading
import time

from process.config import resolve_data, setting
from process.memory import store

MIN_CHARS = 20           # shorter messages aren't about anything
WORD_MATCH = 0.34        # share of the message's telling words found in the episode
MEANING_MATCH = 0.62     # cosine similarity, for bge-small style models
REST = 12                # replies before the same episode can come up again

_lock = threading.Lock()
_turn = 0
_last = {}               # episode id -> turn it last came up
_embed_down_until = 0.0

_DULL = set("""about after again also because been before being could does doing done
don't from going have having here just know like make more much really said should
some than that that's their them then there these they thing things think this those
today want well were what when where which while will with would yeah your you're""".split())


def enabled():
    return bool(setting("recall", "enabled", True)) and bool(setting("llm", "recall", True))


def _words(text):
    return {w for w in re.findall(r"[a-z0-9']+", (text or "").lower())
            if len(w) > 3 and w not in _DULL}


def _by_words(message, episodes):
    mine = _words(message)
    if len(mine) < 2:
        return None
    best, score = None, 0.0
    for e in episodes:
        shared_words = mine & _words(e["text"])
        s = len(shared_words) / len(mine)
        if len(shared_words) >= 2 and s > score:
            best, score = e, s
    return best if score >= float(setting("recall", "word_match", WORD_MATCH)) else None


def _vectors_file():
    return resolve_data("episode_vectors.json")


def _embed(texts, model):
    from process.llm_funcs.llm_scr import _clients
    out = _clients["server"].embeddings.create(model=model, input=texts, timeout=4.0)
    return [d.embedding for d in out.data]


def _cosine(a, b):
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _by_meaning(message, episodes, model):
    """The best match by embedding, or None. Raises if the model can't be had."""
    try:
        known = json.loads(_vectors_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        known = {}
    missing = [e for e in episodes if e["id"] not in known]
    if missing:
        for e, v in zip(missing, _embed([e["text"] for e in missing], model)):
            known[e["id"]] = v
        live = {e["id"] for e in episodes}
        _vectors_file().write_text(
            json.dumps({k: v for k, v in known.items() if k in live}), encoding="utf-8")
    query = _embed([message], model)[0]
    best, score = None, 0.0
    for e in episodes:
        s = _cosine(query, known[e["id"]])
        if s > score:
            best, score = e, s
    return best if score >= float(setting("recall", "meaning_match", MEANING_MATCH)) else None


def find(message):
    """The older episode this message brings to mind, or None."""
    global _embed_down_until
    if len(message or "") < MIN_CHARS:
        return None
    older = store.episodes()[:-store.EPISODES_IN_PROMPT]
    if not older:
        return None
    model = str(setting("recall", "embed_model", "") or "").strip()
    if model and time.time() >= _embed_down_until:
        try:
            return _by_meaning(message, older, model)
        except Exception as e:
            _embed_down_until = time.time() + 300
            print(f"[recall] no embeddings ({type(e).__name__}); matching by words", flush=True)
    return _by_words(message, older)


def note(their_message=""):
    """The note for her newest message, or ""."""
    global _turn
    if not enabled() or not isinstance(their_message, str):
        return ""
    with _lock:
        _turn += 1
        now = _turn
    found = find(their_message)
    if not found:
        return ""
    with _lock:
        if now - _last.get(found["id"], -REST) < REST:
            return ""
        _last[found["id"]] = now
    return ("\n\n(Note to you, not from them: this reminds you of something from a "
            f"while back: {store._when(found)}{found['text']} Use it only if it fits, "
            "the way a friend would. Don't retell it.)")


def reset():
    global _turn
    with _lock:
        _turn = 0
        _last.clear()
