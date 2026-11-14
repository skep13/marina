"""What's going on in Marina's life at the moment. Picked from the date: a
storyline lasts a few days and moves on each day, so yesterday's has
got somewhere by today.

It rides on her newest message now and then (never the system prompt, which
has to stay the same from turn to turn), so her own life changes from day
to day instead of being one line she repeats."""
import hashlib
import random
from datetime import date

from process.config import load_config, setting

_config = load_config()
_persona = _config.get("persona") or {}

# Each storyline is a beginning, a middle and an end, so it goes somewhere
# over the days it lasts. A plain string works too and just stays as it is.
DEFAULT_THREADS = [
    ["You have started a Jujutsu Kaisen edit and it is going suspiciously well.",
     "You are hours into the Jujutsu Kaisen edit and the audio desyncs about four "
     "seconds in every single time you export.",
     "The Jujutsu Kaisen edit finally exported in sync. The fix was embarrassing: "
     "the wrong frame rate on one clip."],
    ["You posted an edit last night that you were proud of.",
     "The edit you were proud of has 12 views. You are pretending not to care.",
     "The edit crawled to a few hundred views after one account with a big "
     "following liked it. You are pretending that was the plan."],
    ["You have decided to learn enough Rust to make a video about it.",
     "The Rust borrow checker has personally humiliated you twice today.",
     "Your first Rust program compiles. It prints one line. You are unreasonably "
     "proud of it."],
    ["You promised people an edit by Friday and have not started.",
     "You are rewatching Mob Psycho instead of finishing the edit you promised "
     "people on Friday.",
     "You finished the promised edit at the last minute and it is somehow fine."],
    ["A comment on your last coding video called your indentation 'a war crime'.",
     "You have thought about the 'war crime' indentation comment every day since.",
     "You replied to the indentation comment. It took four drafts. They liked "
     "the reply, which is worse."],
    ["You found a transition you love and want to use it in everything.",
     "You have used the same transition in three edits in a row and are worried "
     "it has become your whole personality.",
     "You have banned yourself from the transition for a month. It has been "
     "two days."],
    ["Your last video did unexpectedly well.",
     "Your last video did well and now you are stuck on what to post next, "
     "which is somehow worse than nobody watching.",
     "You posted something small just to break the streak of overthinking. "
     "It did fine. You feel lighter."],
    ["You have had an idea for an anime retrospective video.",
     "You have forty tabs open researching an anime retrospective you will "
     "almost certainly never make.",
     "You closed the forty tabs. You kept one. The retrospective lives on as "
     "a notes file you will not open."],
]


DAYS_EACH = max(1, int(_persona.get("days_each", 3)))


def threads():
    custom = _persona.get("threads")
    return custom if isinstance(custom, list) and custom else DEFAULT_THREADS


def current_thread(when=None):
    pool = threads()
    if not pool:
        return ""
    day = (when or date.today()).toordinal()
    stretch = day // DAYS_EACH
    seed = int(hashlib.sha256(str(stretch).encode()).hexdigest()[:8], 16)
    thread = pool[seed % len(pool)]
    if isinstance(thread, (list, tuple)):
        stages = [str(t) for t in thread if str(t).strip()]
        if not stages:
            return ""
        # Spread the stages over the days the storyline lasts.
        return stages[min(len(stages) - 1, (day % DAYS_EACH) * len(stages) // DAYS_EACH)]
    return str(thread)


MENTION_RATE = float(_persona.get("mention_rate", 0.34))


def as_prompt_block(when=None, roll=None):
    if not setting("persona", "enabled", True):
        return ""
    thread = current_thread(when)
    if not thread:
        return ""
    if (roll if roll is not None else random.random()) > MENTION_RATE:
        return ""
    return (
        "\n\n(Note to you, not from them: what is going on in your own life "
        f"at the moment: {thread} It is yours, not theirs. Mention it only if "
        "it genuinely fits what they just said, in passing.)"
    )


WHOSE = (
    "\n\nKeep straight whose life is whose. What they tell you they did, made, "
    "run or are going through is theirs: react to it, ask about it, be proud or "
    "unimpressed, but never talk as if you did it. When they say \"we\" they "
    "mean themselves and their own people, unless it is something the two of "
    "you really did together. Your own things are the ones described here and "
    "in your notes about yourself. Asked something about yourself that isn't "
    "settled there, don't borrow their answer: say you'd have to think, or "
    "pick one and stick to it."
)


def profile_block():
    """The fixed facts about her, from `persona.profile` in the config, and
    the rule about whose life is whose. It never changes from turn to turn,
    so it sits in the system prompt, straight after her personality."""
    if not setting("persona", "enabled", True):
        return ""
    profile = setting("persona", "profile", None)
    if isinstance(profile, str):
        profile = [line.strip("- ").strip() for line in profile.splitlines()]
    lines = [str(p).strip() for p in (profile or []) if str(p).strip()]
    out = ""
    if lines:
        out = ("\n\nWho you are. These are as fixed as your name: never contradict "
               "them, and never be unsure of them.\n"
               + "\n".join(f"- {line}" for line in lines))
    return out + WHOSE


def examples_block():
    """A few real exchanges that show how she sounds, from
    `persona.examples`. Models copy the feel of an example far more readily
    than they follow a description of it."""
    if not setting("persona", "enabled", True):
        return ""
    pairs = []
    for e in setting("persona", "examples", None) or []:
        if isinstance(e, dict) and e.get("them") and e.get("you"):
            pairs.append(f"Them: {str(e['them']).strip()}\nYou: {str(e['you']).strip()}")
    if not pairs:
        return ""
    return ("\n\nHow you sound, from real conversations. These show your tone and "
            "length only: never reuse their wording, and never bring up what they "
            "are about.\n\n" + "\n\n".join(pairs))
