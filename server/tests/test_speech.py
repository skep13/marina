"""What she says out loud versus what she performs.

Every case here is a shape a small model actually produced, or the direct
inverse of one. The rule under test is that a stage direction never reaches
the TTS and an emphasised word never goes missing from it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process.text_func.speech import SentenceSplitter, split_reply   # noqa: E402

# (reply, must be spoken, must NOT be spoken, expected animation or None)
CASES = [
    # The regression: a one-word stage direction was read aloud as a word.
    ("*snaps* fine, it's whatever.", ["fine"], ["snaps"], "emote"),
    ("*sighs* i know.", ["i know"], ["sighs"], "sigh"),
    ("*shrugs* dunno.", ["dunno"], ["shrugs"], "shrug"),
    ("*blinks* wait, what?", ["wait"], ["blinks"], None),

    # The inverse: emphasis must survive, or the sentence loses a word.
    ("that edit took *so long* to render.", ["so long", "render"], [], None),
    ("i said *nothing* about that.", ["nothing"], [], None),
    ("it's *that* bad.", ["that"], [], None),
    ("this is *really* annoying.", ["really"], [], None),

    # Multi-word stage directions still work.
    ("*tilts her head* you sure about that?", ["you sure"], ["tilts"], "tilt"),
    ("*rolls her eyes* obviously.", ["obviously"], ["rolls"], "eyeroll"),

    # Brackets are never dialogue; parentheses usually are.
    ("[leans back] nope.", ["nope"], ["leans back"], "lean"),
    ("i think (probably) yes.", ["probably"], [], None),

    # Markdown and emoji never reach the voice.
    ("**bold** and `code` and \U0001F642 done.", ["done"], ["`", "*"], None),
    ("*unclosed action here", [], ["unclosed"], None),
]


# Streaming cuts the reply into speakable pieces as it is written. The rules
# that matter: never lose a word, and never cut inside a stage direction —
# half an asterisk on each side and both halves get read out loud.
STREAM_CASES = [
    "*sighs* fine. i'll look at it. but you owe me, seriously.",
    "it rendered at 3.5 fps which is, frankly, an insult. *rolls her eyes*",
    "*tilts her head* wait. you did what?",
    "no. absolutely not.",
    "hi",
    "yeah ok so the thing is i've been messing with this export all afternoon "
    "and it keeps desyncing about four seconds in and i cannot work out why",
]


def check_stream(failures):
    """Feed each reply through in small deltas, as a model would produce it."""
    for reply in STREAM_CASES:
        for size in (1, 4, 13):
            splitter = SentenceSplitter()
            segments = []
            for i in range(0, len(reply), size):
                segments += splitter.feed(reply[i:i + size])
            tail = splitter.flush()
            if tail:
                segments.append(tail)

            rejoined = " ".join(segments)
            if rejoined.split() != reply.split():
                failures.append(
                    f"{reply!r} at delta={size}\n      text changed: {rejoined!r}")
            for segment in segments:
                if segment.count("*") % 2:
                    failures.append(
                        f"{reply!r} at delta={size}\n      cut inside an action: {segment!r}")


def run():
    failures = []
    check_stream(failures)
    for reply, must, must_not, animation in CASES:
        out = split_reply(reply)
        spoken = out["speech"].lower()

        for phrase in must:
            if phrase.lower() not in spoken:
                failures.append(f"{reply!r}\n      missing {phrase!r} from speech {out['speech']!r}")
        for phrase in must_not:
            if phrase.lower() in spoken:
                failures.append(f"{reply!r}\n      spoke {phrase!r} — should have been performed: {out['speech']!r}")
        if animation:
            got = [c["animation"] for c in out["cues"]]
            if animation not in got:
                failures.append(f"{reply!r}\n      expected a {animation!r} cue, got {got}")

    print(f"  {len(CASES)} split cases + {len(STREAM_CASES) * 3} streaming cases, "
          f"{len(failures)} failures")
    for f in failures:
        print("   FAIL", f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
