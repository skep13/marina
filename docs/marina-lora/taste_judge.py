#!/usr/bin/env python3
"""A judge that picks between two Marina replies the way the owner does.

It is shown the owner's own past picks (picked.jsonl from collect_picks.py)
as examples, then a new pair, in both orders; it only gives a label when both
orders agree. Runs on the `marina` model (Gemma, already loaded) so nothing
swaps out.

  eval:   python3 -I taste_judge.py eval  [N_HELD_OUT]   agreement on held-out picks
  label:  python3 -I taste_judge.py label PAIRS.jsonl... > auto.jsonl
          labels every pair the owner hasn't judged (context, chosen, rejected)
Run in ct110 with KEY set, next to picked.jsonl.
"""
import json, os, random, re, sys, urllib.request

URL = "http://127.0.0.1:8080/v1/chat/completions"
KEY = os.environ.get("KEY", "")
DIR = os.path.dirname(os.path.abspath(__file__))
N_EXAMPLES = 30

TASTE = """What the person wants above all: Marina should sound like a real person
texting them, a girl their age, not a chatbot or a character performing.
What that means in their picks (tendencies, not rules):
- The shorter, tighter reply: people text in a line or two, not paragraphs.
- Casual and natural over polished, clever or written-sounding.
- She still asks things, the way a friend does: curious, teasing, following up
  on what they said. What reads as a chatbot is a polite check-in question
  tacked onto the end of every reply, or two or three questions at once.
- An *action* that shows a feeling, rather than none.
- Replies that answer what they actually said, warmly and in character."""


def post(messages):
    body = {"model": "marina", "messages": messages, "max_tokens": 120, "temperature": 0.0,
            "seed": 1, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {
        "Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["choices"][0]["message"].get("content") or ""


def tail(context, n=3):
    return "\n".join(f"{'Them' if m['role'] == 'user' else 'Marina'}: {m['content']}"
                     for m in context[-n:])


def example(r, rng):
    first_chosen = rng.random() < 0.5
    a, b = (r["chosen"], r["rejected"]) if first_chosen else (r["rejected"], r["chosen"])
    return (f"Chat:\n{tail(r['context'])}\nA: {a}\nB: {b}\nThey picked: "
            f"{'A' if first_chosen else 'B'}")


def prompt(examples, context, a, b):
    rng = random.Random(len(examples))
    shots = "\n\n---\n\n".join(example(r, rng) for r in examples)
    return [{"role": "system", "content":
             "You predict which of two replies from Marina (their companion; *asterisks* are "
             "actions her avatar acts out) one particular person would pick. You have their "
             f"real past picks below. Learn their taste from them.\n\n{TASTE}\n\n"
             f"THEIR PAST PICKS\n\n{shots}"},
            {"role": "user", "content":
             f"New pair.\nChat:\n{tail(context)}\nA: {a}\nB: {b}\n\nWhich would they pick? "
             "Answer with one letter, A or B."}]


def vote(examples, context, x, y):
    """'x', 'y' or None (orders disagree)."""
    def ask(a, b):
        t = post(prompt(examples, context, a, b)).strip().upper()
        m = re.search(r"\b([AB])\b", t)
        return m.group(1) if m else None
    v1 = ask(x, y)
    v2 = ask(y, x)
    first = {"A": "x", "B": "y"}.get(v1)
    second = {"A": "y", "B": "x"}.get(v2)
    return first if first and first == second else None


def main():
    picked = [json.loads(l) for l in open(f"{DIR}/picked.jsonl")]
    mode = sys.argv[1]
    if mode == "eval":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        rng = random.Random(0)
        rng.shuffle(picked)
        held, train = picked[:n], picked[n:]
        right = wrong = abstain = 0
        shorter_right = 0
        for r in held:
            shots = random.Random(r["id"]).sample(train, min(N_EXAMPLES, len(train)))
            v = vote(shots, r["context"], r["chosen"], r["rejected"])
            if v is None:
                abstain += 1
            elif v == "x":
                right += 1
            else:
                wrong += 1
            shorter_right += len(r["chosen"].split()) < len(r["rejected"].split())
            print(f"{r['id']}: {'abstain' if v is None else 'right' if v == 'x' else 'WRONG'}",
                  flush=True)
        print(f"\nheld out {n}: right {right}, wrong {wrong}, no call {abstain}; "
              f"agreement when it calls: {right / max(1, right + wrong):.0%}; "
              f"'pick the shorter' baseline: {shorter_right}/{n}", flush=True)
    elif mode == "label":
        judged = {r["id"] for r in picked}
        skip = set(json.loads(os.environ.get("SKIP_IDS", "[]")))
        for path in sys.argv[2:]:
            for line in open(path):
                p = json.loads(line)
                if p["id"] in judged or p["id"] in skip:
                    continue
                shots = random.Random(p["id"]).sample(picked, min(N_EXAMPLES, len(picked)))
                v = vote(shots, p["context"], p["a"], p["b"])
                if v is None:
                    continue
                c, r = (p["a"], p["b"]) if v == "x" else (p["b"], p["a"])
                print(json.dumps({"id": p["id"], "context": p["context"], "chosen": c,
                                  "rejected": r, "auto": True}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
