"""Keeping her from repeating herself.

A model with its own last few replies in front of it tends to copy them: the
same opener ("oh wow it's saturday night and you're still awake!"), the same
template ("ugh that sucks lol. at least ... right?"), the same filler. Sampling
penalties only catch exact tokens, so each reply also gets a short note
naming what she has been leaning on lately, and asking her not to.

The note goes on the newest message (like the clock), never into the system
prompt, so the server's cached prefix stays the same from turn to turn.
"""
import re
from collections import Counter

LOOK_BACK = 8          # her replies to look at
OPENER_WORDS = 4       # how much of a reply counts as its opener
PHRASE_WORDS = 4       # a repeated phrase is this many words or more
TIC_SHARE = 0.4        # a filler in at least this share of her last 5 replies is a tic

# Words that make a 4-word run look repeated when it's just grammar.
_PLAIN = set("i you it the a an and to of is that this so but what just my your me "
             "be are was in on for with at do have not like yeah oh".split())
_FILLERS = ["lol", "lmao", "haha", "omg", "ugh", "honestly", "actually", "literally",
            "oh wow", "wait", "right?", "??", "at least", "even though"]


def _text(m):
    c = m.get("content")
    if isinstance(c, list):
        c = " ".join(p.get("text", "") for p in c if isinstance(p, dict))
    return str(c or "")


def _words(s):
    return re.findall(r"[a-z0-9']+", s.lower())


def _recent(history):
    out = [_text(m) for m in history if m.get("role") == "assistant"]
    return [t for t in out if t.strip()][-LOOK_BACK:]


def openers(replies):
    seen, out = set(), []
    for r in reversed(replies):
        w = _words(r)[:OPENER_WORDS]
        if len(w) >= 3:
            key = " ".join(w)
            if key not in seen:
                seen.add(key)
                out.append(key)
    return out[:4]


def repeated_phrases(replies):
    """Runs of PHRASE_WORDS words that show up in two or more replies, one per
    habit: phrases found in exactly the same replies are one habit, and what
    the opener list already names is left out."""
    where = {}
    for i, r in enumerate(replies):
        w = _words(r)
        for j in range(len(w) - PHRASE_WORDS + 1):
            g = " ".join(w[j:j + PHRASE_WORDS])
            if sum(x not in _PLAIN for x in g.split()) >= 2:
                where.setdefault(g, set()).add(i)
    starts = {" ".join(_words(r)[:PHRASE_WORDS]) for r in replies}
    habits = {}
    for g, found in where.items():
        if len(found) < 2 or g in starts:
            continue
        key = frozenset(found)
        best = habits.get(key)
        if best is None or sum(x not in _PLAIN for x in g.split()) > sum(x not in _PLAIN for x in best.split()):
            habits[key] = g
    ranked = sorted(habits.items(), key=lambda kv: -len(kv[0]))
    out = []
    for _, g in ranked:
        if not any(len(set(g.split()) & set(o.split())) >= 2 for o in out):
            out.append(g)
    return out[:4]


# Common words long enough to look like a subject.
_COMMON = set("""about after again all also always another anything around because been before
being better bit could didn't doesn't doing don't else even ever every feel feeling first going
gonna good great guess have here honestly i'll i'm it's just kind know last least like little
long looks make maybe mean more most much need never night only other people pretty probably
really right said same says should since something sounds still sure take thank thanks that's
there there's these thing things think though time today tonight totally very want wanna well
were what's when where which while whole why will with would yeah yet you'd you'll you're
you've your actually literally anyway okay haha lmao""".split())


def topics(replies, their_words=()):
    """Subjects she has raised in most of her recent replies (and that they
    aren't talking about right now): what makes her sound like a loop even
    when the wording changes."""
    if len(replies) < 3:
        return []
    count = Counter()
    for r in replies[-5:]:
        for w in set(_words(r)):
            if (len(w) >= 5 or w.isdigit()) and w not in _COMMON and w not in _PLAIN:
                count[w] += 1
    need = 3 if len(replies[-5:]) >= 4 else 2
    their = set(their_words)
    return [w for w, n in count.most_common() if n >= need and w not in their][:3]


def tics(replies):
    if len(replies) < 3:
        return []
    low = [r.lower() for r in replies[-5:]]
    out = []
    for f in _FILLERS:
        pat = re.escape(f) if not f[0].isalnum() else r"\b" + re.escape(f).rstrip(r"\?") + r"\b"
        n = sum(1 for r in low if re.search(pat, r))
        if n / len(low) >= TIC_SHARE:
            out.append(f)
    return out


def note(history, their_message=""):
    """A note to add to her newest message, or "" if she's been varied.
    `their_message` is what they just said: subjects they bring up are fair."""
    replies = _recent(history)
    if len(replies) < 2:
        return ""
    parts = []
    ops = openers(replies)
    if ops:
        parts.append("your recent replies started: " + "; ".join(f'"{o}…"' for o in ops)
                     + ". Start this one a different way")
    rep = repeated_phrases(replies)
    if rep:
        parts.append("don't reuse these phrases you keep coming back to: "
                     + "; ".join(f'"{p}"' for p in rep))
    subj = topics(replies, _words(their_message if isinstance(their_message, str) else ""))
    if subj:
        parts.append("you've brought up " + ", ".join(f'"{t}"' for t in subj)
                     + " in most of your recent replies; leave that alone unless they raise it")
    tic = tics(replies)
    if tic:
        parts.append("go easy on " + ", ".join(f'"{t}"' for t in tic)
                     + ", you've leaned on them a lot lately")
    if not parts:
        return ""
    return ("\n\n(Note to you, not from them: don't repeat yourself. "
            + "; ".join(parts)
            + ". Respond to what they actually just said, in fresh words.)")
