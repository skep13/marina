"""What is worth keeping as a lasting fact, and what is not.

Every rejected case is a shape the model actually stored as a "memory" before
the validator existed: an instruction to itself, passing state, or its own
narration. The accepted cases are ordinary facts about the user.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from process.memory.store import _is_durable_fact  # noqa: E402

REJECT = [
    "Say hello to elekryo, one of my TikTok followers.",
    "Marina says hi and thats one of her TikTok followers!",
    "(Marina is currently talking to elektrikryo, a person on my tiktok follower list)",
    "I couldn't be bothered to offer suggestions and was annoyed when you asked.",
    "remind me to call mum",
    "we are currently talking about anime",
    "tell them about the new episode",
    "I love this song",
    "what is on the clipboard?",
    "no",
]
ACCEPT = [
    "The user's name is Jacob",
    "the user is building a friend not an assistant",
    "Jacob is learning Rust",
    "Jacob works as a software engineer",
    "The user has a cat named Milo",
    "Jacob lives in the UK",
]


def run():
    fails = []
    for t in REJECT:
        if _is_durable_fact(t):
            fails.append(f"should REJECT but kept: {t!r}")
    for t in ACCEPT:
        if not _is_durable_fact(t):
            fails.append(f"should ACCEPT but dropped: {t!r}")
    print(f"  {len(REJECT)} reject + {len(ACCEPT)} accept cases, {len(fails)} failures")
    for f in fails:
        print("   FAIL", f)
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(run())
