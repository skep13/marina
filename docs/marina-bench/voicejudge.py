#!/usr/bin/env python3
"""Marina voice judge (2026-11-27): which model sounds more like HER?

voicebench.py counts habits (head tilts, long actions, assistant-speak). This
asks a judge from another model family to read two versions of the same chat
blind, against her real persona, and say which is funnier, snarkier, more
charming, more like a real person, a better listener and more Marina.

Each chat pair is judged twice with the sides swapped, which cancels the
judge's lean toward whichever it reads first; a side wins a pair only when
both orders agree, otherwise it's a tie.

Runs inside ct110 after voicebench.py, on its output in /root/bench/voice.
Usage:  voicejudge.py [-j JUDGE] [MODEL_A MODEL_B]   (default: marina marina-voice,
        judge "browser" = Qwen3.6-35B-A3B in llama-swap)
        voicejudge.py --taste [--picks picks.txt]   one question, judged by the
        owner's taste (from their blind picks), reasoning first; with --picks it
        also scores how often it agrees with those picks
Output: /root/bench/voice/judge.json and judge.txt (judge-taste.* with --taste)
"""
import argparse, collections, json, re, subprocess, time, urllib.request

DIR = "/root/bench/voice"
URL = "http://127.0.0.1:8080/v1/chat/completions"
CRITERIA = {
    "funnier": "Which Marina is funnier: real jokes and wit that land, not just saying 'haha'?",
    "snarkier": "Which has better snark with warmth underneath: teasing, unimpressed, opinionated, "
                "without being mean or flat?",
    "charm": "Which has more of her playful, sweet, slightly flirty charm and a little mystery?",
    "real_person": "Which sounds more like a real girl texting a friend, and less like an AI "
                   "or a character performing?",
    "listener": "Which reacts better to what they actually said and follows where they take the chat?",
    "in_character": "Which is closer to Marina as the persona describes her, rules included "
                    "(short, few actions, not ending every reply with a question, no therapist voice)?",
    "overall": "Overall, which would the person rather be chatting with?",
}

JUDGE_PROMPT = """You judge how well a character is written. Below is the persona of Marina, a
companion who chats by text and video call with one person (it is read out
loud and acted by an avatar). Then two versions of the same chat: the person's
messages are identical, Marina's replies were written by two different models.

Judge only Marina's replies. Ignore which version is longer; longer is not
better, and the persona asks for short. Things in *asterisks* are actions the
avatar acts out. Be decisive: say "tie" only when they are truly level.

PERSONA
-------
{persona}
-------

{chats}

For each question answer "A", "B" or "tie":
{questions}

Reply with JSON only, no other text:
{{{keys}, "why": "one sentence on the biggest difference"}}"""


# What the owner picked when they judged 30 chats blind (2026-11-27). Written
# as general taste, not per chat, so it can judge new chats too.
TASTE = """HOW THE PERSON JUDGES (their own taste, from their blind picks):
- She has energy and takes the lead when the chat goes slow: she suggests
  something to do, picks a direction, gets things moving. A reply that just
  answers and hands the turn back loses to one that drives.
- Gestures that show a feeling win: getting flustered, faking betrayal,
  laughing and looking away. A reply with no *action* feels flatter, and a
  stock one (*rolls eyes* every time) is weak.
- Teasing is soft underneath, tsundere: "in your dreams... ok maybe it was a
  bit boring without you" beats a flat "no way". Never actually cold or mean.
- When they are tired, sad or stressed she goes gentle first: soft, caring,
  close (reaching toward the screen). Teasing them while they are down loses.
- Asked if she is an AI, she laughs it off cheekily and turns it back on
  them; getting annoyed or defensive loses.
- Assistant habits lose: check-in questions tacked on the end ("is everything
  else working okay?", "how was your day?"), offering help, explaining.
  When she does ask something, it is curious or teasing, not polite.
- Short and punchy beats long. One good line beats three okay ones."""

TASTE_PROMPT = """You are picking which of two versions of a chat one particular person
would rather have. Marina is their companion: she texts and video-calls with
them (read out loud and acted by an avatar; *asterisks* are actions). The
person's messages are identical in both versions; Marina's replies differ.

PERSONA (who Marina is)
-------
{persona}
-------

{taste}

{chats}

Go through the chat turn by turn and note, briefly, where each version does
better by the person's taste above. Then decide. Say "tie" only when they are
truly level. Reply with JSON only, no other text:
{{"notes": "two or three sentences comparing them", "winner": "A|B|tie"}}"""


def post(model, key, messages, max_tokens=300):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0.2,
            "seed": 7, "chat_template_kwargs": {"enable_thinking": False}}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {
        "Content-Type": "application/json", "Authorization": "Bearer " + key})
    with urllib.request.urlopen(req, timeout=900) as r:
        return json.load(r)["choices"][0]["message"].get("content") or ""


def chat_text(label, turns):
    lines = [f"VERSION {label}"]
    for t in turns:
        lines += [f"Them: {t['user']}", f"Marina: {t['reply']}"]
    return "\n".join(lines)


def parse(text):
    m = re.search(r"\{.*\}", text, re.S)
    try:
        d = json.loads(m.group(0)) if m else {}
    except ValueError:
        d = {}
    return {c: str(d.get(c, "")).strip().upper().replace("TIE", "tie") for c in CRITERIA} | \
           {"why": d.get("why", "")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", default=["marina", "marina-voice"])
    ap.add_argument("-j", "--judge", default="browser")
    ap.add_argument("--taste", action="store_true")
    ap.add_argument("--picks", help="owner's picks: lines of 'scenario run plain|voice|tie'")
    a = ap.parse_args()
    if a.taste:
        return taste_main(a)
    ma, mb = a.models
    key = subprocess.run("grep -A1 apiKeys: /opt/llama-swap/config.yaml | tail -1 | "
                         "tr -d ' \"-' | cut -d# -f1", shell=True, capture_output=True,
                         text=True).stdout.strip()
    system = json.load(open(f"{DIR}/snapshot.json"))["system"]
    persona = system.split("You remember these things about the user")[0].strip()

    def convos(model):
        out = collections.defaultdict(list)
        for r in json.load(open(f"{DIR}/{model}.json"))["chats"]:
            out[(r["run"], r["scenario"])].append(r)
        return out
    ca, cb = convos(ma), convos(mb)
    questions = "\n".join(f'- {c}: {q}' for c, q in CRITERIA.items())
    keys = ", ".join(f'"{c}": "A|B|tie"' for c in CRITERIA)

    results, t0 = [], time.time()
    for k in sorted(ca):
        if k not in cb:
            continue
        verdicts = []
        for first, second in ((ma, mb), (mb, ma)):
            chats = "\n\n".join([chat_text("A", (ca if first == ma else cb)[k]),
                                 chat_text("B", (cb if first == ma else ca)[k])])
            raw = post(a.judge, key, [{"role": "user", "content": JUDGE_PROMPT.format(
                persona=persona, chats=chats, questions=questions, keys=keys)}])
            v = parse(raw)
            # Name the winner by model, not by letter.
            named = {c: {"A": first, "B": second}.get(v[c], "tie") for c in CRITERIA}
            verdicts.append({"order": [first, second], "named": named, "why": v["why"], "raw": raw[:600]})
        final = {c: (verdicts[0]["named"][c] if verdicts[0]["named"][c] == verdicts[1]["named"][c]
                     else "tie") for c in CRITERIA}
        results.append({"run": k[0], "scenario": k[1], "final": final, "verdicts": verdicts})
        print(f"[{time.time() - t0:.0f}s] r{k[0]} {k[1]}: overall={final['overall']} | "
              f"{verdicts[0]['why'][:90]!r}", flush=True)

    lines = [f"Judge {a.judge}: {ma} vs {mb}, {len(results)} chats, each judged in both orders",
             f"(a side wins a chat only when both orders agree; otherwise tie)", ""]
    for c in CRITERIA:
        n = collections.Counter(r["final"][c] for r in results)
        agree = sum(r["verdicts"][0]["named"][c] == r["verdicts"][1]["named"][c] for r in results)
        lines.append(f"{c:13} {mb} {n[mb]:2}  {ma} {n[ma]:2}  tie {n['tie']:2}   "
                     f"(orders agreed {100 * agree // max(1, len(results))}%)")
    lines += ["", "By scenario (overall):"]
    for scen in sorted({r["scenario"] for r in results}):
        n = collections.Counter(r["final"]["overall"] for r in results if r["scenario"] == scen)
        lines.append(f"  {scen:17} {mb} {n[mb]}  {ma} {n[ma]}  tie {n['tie']}")
    text = "\n".join(lines)
    json.dump(results, open(f"{DIR}/judge.json", "w"), indent=1, ensure_ascii=False)
    open(f"{DIR}/judge.txt", "w").write(text + "\n")
    print("\n" + text + "\n\n== VOICEJUDGE DONE", flush=True)


def taste_main(a):
    ma, mb = a.models
    key = subprocess.run("grep -A1 apiKeys: /opt/llama-swap/config.yaml | tail -1 | "
                         "tr -d ' \"-' | cut -d# -f1", shell=True, capture_output=True,
                         text=True).stdout.strip()
    system = json.load(open(f"{DIR}/snapshot.json"))["system"]
    persona = system.split("You remember these things about the user")[0].strip()
    side = {ma: "plain", mb: "voice"}

    def convos(model):
        out = collections.defaultdict(list)
        for r in json.load(open(f"{DIR}/{model}.json"))["chats"]:
            out[(str(r["run"]), r["scenario"])].append(r)
        return out
    ca, cb = convos(ma), convos(mb)
    picks = {}
    if a.picks:
        for line in open(a.picks):
            if line.strip() and not line.startswith("#"):
                scen, run, w = line.split()
                picks[(run, scen)] = w

    results, t0 = [], time.time()
    for k in sorted(ca):
        if k not in cb:
            continue
        votes = []
        for first, second in ((ma, mb), (mb, ma)):
            chats = "\n\n".join([chat_text("A", (ca if first == ma else cb)[k]),
                                 chat_text("B", (cb if first == ma else ca)[k])])
            raw = post(a.judge, key, [{"role": "user", "content": TASTE_PROMPT.format(
                persona=persona, taste=TASTE, chats=chats)}], max_tokens=500)
            m = re.search(r"\{.*\}", raw, re.S)
            try:
                d = json.loads(m.group(0)) if m else {}
            except ValueError:
                d = {}
            w = str(d.get("winner", "")).strip().upper()
            votes.append({"order": [first, second], "winner": {"A": first, "B": second}.get(w, "tie"),
                          "notes": d.get("notes", ""), "raw": raw[:800]})
        final = votes[0]["winner"] if votes[0]["winner"] == votes[1]["winner"] else "tie"
        r = {"run": k[0], "scenario": k[1], "final": final, "votes": votes}
        if k in picks:
            r["owner"] = picks[k]
        results.append(r)
        print(f"[{time.time() - t0:.0f}s] r{k[0]} {k[1]}: {final}"
              + (f" (owner: {picks[k]})" if k in picks else ""), flush=True)

    n = collections.Counter(side.get(r["final"], "tie") for r in results)
    lines = [f"Taste judge {a.judge}: {ma} (plain) vs {mb} (voice), {len(results)} chats, both orders",
             f"plain {n['plain']}  voice {n['voice']}  tie {n['tie']}"]
    scored = [r for r in results if "owner" in r]
    if scored:
        decided = [r for r in scored if r["final"] != "tie"]
        agree = sum(side[r["final"]] == r["owner"] for r in decided)
        lean = collections.Counter(side.get(v["winner"], "tie") == r["owner"]
                                   for r in scored for v in r["votes"])
        lines += [f"agrees with the owner on {agree} of {len(decided)} decided chats "
                  f"({len(scored) - len(decided)} ties)",
                  f"single-order votes matching the owner: {lean[True]} of {2 * len(scored)}"]
        lines += ["", "Disagreements:"] + [
            f"  {r['scenario']} r{r['run']}: judge {side[r['final']]}, owner {r['owner']}"
            for r in decided if side[r["final"]] != r["owner"]]
    text = "\n".join(lines)
    json.dump(results, open(f"{DIR}/judge-taste.json", "w"), indent=1, ensure_ascii=False)
    open(f"{DIR}/judge-taste.txt", "w").write(text + "\n")
    print("\n" + text + "\n\n== VOICEJUDGE DONE", flush=True)


if __name__ == "__main__":
    main()
