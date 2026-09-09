"""What she says out loud versus what she performs.

Every case here is a shape a small model actually produced, or the direct
inverse of one. The rule under test is that a stage direction never reaches
the TTS and an emphasised word never goes missing from it.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process.text_func.speech import split_reply      # noqa: E402

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
    ("**bold** and `code` and 🙂 done.", ["done"], ["`", "*"], None),
    ("*unclosed action here", [], ["unclosed"], None),
]


def run():
    failures = []
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

    print(f"  {len(CASES)} cases, {len(failures)} failures")
    for f in failures:
        print("   FAIL", f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
