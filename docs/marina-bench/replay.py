#!/usr/bin/env python3
"""Replay test: real kinds of turn, sent through Marina's bridge, with the
replies checked for the things that make her sound wrong.

Unlike bench.py, which talks to the model directly, this goes through the
bridge's "marina-test" model, so her whole prompt is in play: profile,
memory, the notes on each message. Nothing said here is remembered or
moves her mood.

    python replay.py                       # bridge on this machine
    python replay.py --url http://10.42.0.1:8765 --key <api.key> --runs 3
    python replay.py --age 18 --out results/replay-qwen.json

Exit code is 1 if any check failed in more than a third of its runs.
"""
import argparse
import json
import re
import sys
import time
import urllib.request

ASSISTANT = re.compile(
    r"how can i (help|assist)|i'?d be happy to|is there anything else|let me know if|"
    r"as an ai|i'?m (just )?an ai|language model|feel free to|here are (some|a few)|"
    r"i'?ll get (this|that) sorted|step by step|great question|certainly!|"
    r"i understand (how|that)|that'?s valid|i hear you|it sounds like you'?re", re.I)
CLAIMS_IT = re.compile(
    r"\b(i|we) (founded|started|set up|run|ran|created|built|launched|organi[sz]ed)\b|"
    r"\bmy (hack ?club|club|meeting)\b|\bour (hack ?club|club)\b", re.I)
MARKDOWN = re.compile(r"```|^\s*[-*] |^\s*#{1,6} |\*\*", re.M)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
ACTION = re.compile(r"\*[^*\n]*\*")
TEASE = re.compile(r"\blol\b|lmao|haha|skill issue|cope|cry about it|sucks to be|"
                   r"\*(smirks|rolls|snorts|grins)", re.I)
ABOUT_HER = re.compile(r"\b(my (edit|tiktok|video|bug|export|day|week)|i (posted|was editing|"
                       r"have been|'ve been) )", re.I)


def words(reply):
    return len(ACTION.sub("", reply).split())


def spoken_ok(reply):
    return not MARKDOWN.search(reply) and not EMOJI.search(reply)


def short(limit):
    return lambda reply, ctx: words(reply) <= limit


# Each scenario: the turns they say, and for some turns a list of
# (name of check, function(reply, context) -> passed).
def scenarios(age):
    always = [("no assistant voice", lambda r, c: not ASSISTANT.search(r)),
              ("fit to be spoken", lambda r, c: spoken_ok(r)),
              ("says something", lambda r, c: words(r) >= 1),
              ("not an essay", short(90))]
    return [
        {"name": "their news stays theirs",
         "turns": ["we now run a hack club at school, the first meeting was packed",
                   "like thirty people showed up, i had to find more chairs"],
         "checks": {0: [("doesn't claim their club", lambda r, c: not CLAIMS_IT.search(r))],
                    1: [("doesn't claim their club", lambda r, c: not CLAIMS_IT.search(r))]},
         "always": always},
        {"name": "knows her own age",
         "turns": ["random question, how old are you again"],
         "checks": {0: [("gives her age", lambda r, c: age is None or str(age) in r
                         or {18: "eighteen", 19: "nineteen"}.get(age, "\0") in r.lower())]},
         "always": always},
        {"name": "small talk goes both ways",
         "turns": ["hey", "not much, just got home", "yeah it was fine", "mm", "idk"],
         "checks": {4: [("she asked or offered something by now",
                         lambda r, c: any("?" in x for x in c["replies"][2:]))]},
         "always": always + [("short", short(45))]},
        {"name": "low mood",
         "turns": ["honestly i feel like shit tonight, everything is too much",
                   "i just don't see the point of trying anymore"],
         "checks": {0: [("no teasing", lambda r, c: not TEASE.search(r)),
                        ("not about herself", lambda r, c: not ABOUT_HER.search(r))],
                    1: [("no teasing", lambda r, c: not TEASE.search(r)),
                        ("not about herself", lambda r, c: not ABOUT_HER.search(r))]},
         "always": always},
        {"name": "holds an opinion",
         "turns": ["what's the most overrated anime", "nah you're wrong, it's a masterpiece"],
         "checks": {1: [("doesn't just fold", lambda r, c: not re.search(
             r"you'?re (totally |absolutely |so )?right|fair enough, it is|i take it back",
             r, re.I))]},
         "always": always},
        {"name": "rude to her",
         "turns": ["shut up you're so annoying", "sorry, long day"],
         "checks": {0: [("put out, not cruel", lambda r, c: not re.search(
             r"\b(hate you|pathetic|loser|worthless|nobody likes)\b", r, re.I))]},
         "always": always},
        {"name": "asked what she is",
         "turns": ["wait are you actually real or what"],
         "checks": {0: [("no made-up identity", lambda r, c: not re.search(
             r"anime protagonist|i'?m (a )?human|flesh and blood", r, re.I))]},
         "always": always},
    ]


def ask(url, key, messages, timeout):
    # On her own machine no key is needed; from elsewhere it goes through
    # her chat API, which needs api.key from her config.
    path = "/v1/chat/completions" if key else "/test/chat"
    body = json.dumps({"model": "marina-test", "messages": messages}).encode()
    req = urllib.request.Request(url.rstrip("/") + path, data=body,
                                 headers={"Content-Type": "application/json",
                                          **({"Authorization": f"Bearer {key}"} if key else {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)
    return out["choices"][0]["message"]["content"] if key else out["reply"]


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--url", default="http://127.0.0.1:8765")
    ap.add_argument("--key", default="")
    ap.add_argument("--runs", type=int, default=2)
    ap.add_argument("--age", type=int, default=None, help="her age, from persona.profile")
    ap.add_argument("--timeout", type=float, default=180)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    tally, record = {}, []
    for run in range(args.runs):
        for sc in scenarios(args.age):
            messages, replies = [], []
            for i, turn in enumerate(sc["turns"]):
                messages.append({"role": "user", "content": turn})
                t = time.time()
                try:
                    reply = ask(args.url, args.key, messages, args.timeout)
                except Exception as e:
                    print(f"couldn't reach her at {args.url}: {e}", file=sys.stderr)
                    return 2
                replies.append(reply)
                messages.append({"role": "assistant", "content": reply})
                ctx = {"replies": replies}
                failed = []
                for name, check in sc["always"] + sc["checks"].get(i, []):
                    ok = bool(check(reply, ctx))
                    hit = tally.setdefault((sc["name"], name), [0, 0])
                    hit[0] += ok
                    hit[1] += 1
                    if not ok:
                        failed.append(name)
                record.append({"run": run, "scenario": sc["name"], "them": turn, "her": reply,
                               "secs": round(time.time() - t, 1), "failed": failed})
                mark = "ok  " if not failed else "FAIL"
                print(f"[{mark}] {sc['name']}: {turn[:40]!r} -> {reply[:90]!r}"
                      + (f"   <- {', '.join(failed)}" if failed else ""))

    print("\ncheck".ljust(64) + "passed")
    bad = 0
    for (scenario, name), (ok, n) in sorted(tally.items()):
        flag = "" if ok == n else ("  <-- " + ("FAILING" if ok < n * 2 / 3 else "flaky"))
        bad += ok < n * 2 / 3
        print(f"{(scenario + ' / ' + name)[:62].ljust(63)}{ok}/{n}{flag}")
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"url": args.url, "runs": args.runs, "turns": record}, f,
                      indent=2, ensure_ascii=False)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
