#!/usr/bin/env python3
"""Reply pairs for the owner to judge: one chat, two candidate replies a turn.

The simulator texts like the owner: a style profile measured on their real
messages plus a fresh sample of those messages as examples (user_msg). At each of Marina's
turns, plain Gemma on her live prompt, tools and samplers writes two replies
with different seeds; both must pass gen.py's checks (up to three tries each)
and differ. The pair is saved with the chat so far, then the chat goes on
with one of the two picked at random, so later pairs have a real history.

The owner picks the reply they prefer on the picking page; those picks
become preference data for the adapter (modal_train.py's dpo step).

Usage (in ct110, next to gen.py and snapshot.json):
  KEY=... python3 -I pairgen.py [TARGET_PAIRS] [MAX_HOURS]
Output: /root/marina-lora/pairs.jsonl, one pair a line (appends; restartable).
"""
import json, os, random, re, sys, time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # python -I drops it
sys.argv = sys.argv[:1] + ["0", "0"] + sys.argv[1:]              # gen.py reads argv[1:3]
import gen                                                         # noqa: E402
import inspect                                                     # noqa: E402
MARINA_KW = {"slot": 0} if "slot" in inspect.signature(gen.marina_turn).parameters else {}
USER_KW = {"slot": 1} if "slot" in inspect.signature(gen.user_turn).parameters else {}
TARGET = int(sys.argv[3]) if len(sys.argv) > 3 else 300
MAX_HOURS = float(sys.argv[4]) if len(sys.argv) > 4 else 8
OUT = os.environ.get("PAIRS_OUT", f"{gen.DIR}/pairs.jsonl")


# How the owner actually texts, measured on their 454 real messages to her
# (real_chats.json): short, capitalised by autocorrect, no full stop, curly
# apostrophes, stretched words, almost no slang or emoji, plain and sincere.
STYLE = """How they text (measured from their real messages, follow it closely):
- Short. Usually 2 to 10 words, rarely over 15. One line.
- First letter capitalised (phone autocorrect), then normal case.
- No full stop at the end. A question mark when asking. Hardly ever "!".
- Now and then a stretched word: "Yepppp", "Goodnightttt", "I’m gooddd".
- Almost no slang: no "ngl", "tbh", "fr", "lowkey", "omg", "bro"; "lol"
  very rarely. No emoji.
- Plain and direct, warm with her, sometimes affectionate or honest about how
  they feel, sometimes just "Nope", "Maybe", "I am". Calls her Mari or Marina
  now and then. Swears only occasionally.
- Not dramatic, not performing, no jokes about dying or being dead."""
OLD = re.compile(r"\b(ai|bot|songbird|model|llm|gpu|server|tool|code|screen share|share screen)\b", re.I)
_REAL = []


def real_examples(k=30):
    """A fresh sample of their real messages each call, as style examples only
    (the chats are from before her current persona, so no old topics)."""
    if not _REAL:
        for sess in json.load(open(f"{gen.DIR}/real_chats.json")):
            for m in sess:
                t = m["content"].strip()
                if m["role"] == "user" and t and "\n" not in t and not re.search(r"https?://", t) \
                        and not OLD.search(t) and len(t.split()) <= 25:
                    _REAL.append(t)
    return random.sample(_REAL, min(k, len(_REAL)))


EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")


def styled(text):
    """Mechanical fixes the simulator keeps getting wrong."""
    t = EMOJI.sub("", text).strip().strip('"').strip()
    t = re.sub(r"^(them|me|user|you)\s*:\s*", "", t, flags=re.I)
    t = t.replace("'", "’").split("\n")[0].strip()
    if t.endswith(".") and not t.endswith(".."):
        t = t[:-1]
    return t[:1].upper() + t[1:]


def user_msg(seed, convo):
    lines = "\n".join(f"{'Them' if m['role'] == 'user' else 'Marina'}: {m['content']}"
                      for m in convo[-8:])
    examples = "\n".join(f"- {e}" for e in real_examples())
    prompt = ("You write the text messages of one person chatting with Marina, a girl who is "
              "their close friend (and a bit more), on a video-call app.\n\nAbout them:\n"
              + gen.ABOUT_USER + f"\n\nRight now: {seed['topic']}. Mood: {seed['mood']}."
              f"\n\n{STYLE}\n\nReal messages they have sent her (style only, don't reuse "
              "the content):\n" + examples +
              "\n\nWrite ONLY their next message: no name, no quotes, no *actions*.")
    task = ("Write their first message, starting the chat." if not convo else
            f"The chat so far:\n{lines}\n\nWrite their next message. Reply to what Marina "
            "just said, or drift the way people do; a short sign-off is fine if it has run its course.")
    out = gen.post({"model": gen.MODEL, "max_tokens": 60, "temperature": 0.9, "top_p": 0.95,
                    "seed": random.randrange(1 << 30), **({"id_slot": 1} if USER_KW else {}),
                    "messages": [{"role": "system", "content": prompt},
                                 {"role": "user", "content": task}],
                    "chat_template_kwargs": {"enable_thinking": False}})
    return styled(out.get("content") or "")


def start(text):
    """Her opening gesture, or her first three words: two replies that start
    alike read as the same reply to the owner, so the pair says nothing."""
    m = re.match(r"\s*\*([^*\n]+)\*", text)
    return m.group(1).strip().lower() if m else gen.opener(text)


def reply(convo, previous, unlike=None, tries=3):
    for _ in range(tries):
        msg = gen.marina_turn(convo, **MARINA_KW)
        text = (msg.get("content") or "").strip()
        if msg.get("tool_calls") or gen.why_bad(text, previous):
            continue
        if unlike and start(text) == start(unlike):
            continue
        return text
    return None


def main():
    done = sum(1 for _ in open(OUT)) if os.path.exists(OUT) else 0
    chat_id = 1 + max([json.loads(l)["chat"] for l in open(OUT)] or [-1]) if done else 0
    f, t0 = open(OUT, "a"), time.time()
    print(f"resuming at {done} pairs; target {TARGET}", flush=True)
    while done < TARGET and time.time() - t0 < MAX_HOURS * 3600:
        seed = {"topic": random.choice(gen.TOPICS), "mood": random.choice(gen.MOODS),
                "turns": random.randint(2, 5)}
        convo, previous = [], []
        try:
            for turn in range(seed["turns"]):
                u = user_msg(seed, convo)
                if not u:
                    break
                convo.append({"role": "user", "content": u})
                a = reply(convo, previous)
                b = reply(convo, previous + [a], unlike=a, tries=5) if a else None
                if not a or not b or a == b:
                    break
                f.write(json.dumps({"id": int(os.environ.get("ID_BASE", "0")) + done, "chat": chat_id, "turn": turn, "seed": seed,
                                    "context": convo, "a": a, "b": b},
                                   ensure_ascii=False) + "\n")
                f.flush()
                done += 1
                keep = random.choice((a, b))
                convo.append({"role": "assistant", "content": keep})
                previous.append(keep)
                if done >= TARGET:
                    break
        except Exception as e:
            print(f"error: {e!r}; waiting 30 s", flush=True)
            if os.environ.get("FAIL_FAST"):
                raise
            time.sleep(30)
        chat_id += 1
        print(f"{time.strftime('%H:%M')} {done}/{TARGET} pairs, chat {chat_id}, "
              f"{(time.time() - t0) / 60:.0f} min", flush=True)
    print("== PAIRS DONE", done, flush=True)


def main_real():
    """Pairs at the owner's real messages (real_chats.json from real_chats.py):
    the real chat so far as context, two fresh replies from her to compare."""
    out = os.environ.get("PAIRS_OUT", f"{gen.DIR}/pairs-real.jsonl")
    sessions = json.load(open(f"{gen.DIR}/real_chats.json"))
    done_ids = set()
    if os.path.exists(out):
        done_ids = {(r["chat"], r["turn"]) for r in map(json.loads, open(out))}
    spots = [(si, i) for si, s in enumerate(sessions) for i, m in enumerate(s)
             if m["role"] == "user" and not re.search(r"https?://", m["content"])]
    random.Random(7).shuffle(spots)
    f, t0, made = open(out, "a"), time.time(), len(done_ids)
    print(f"{len(spots)} real messages, {made} done; target {TARGET}", flush=True)
    for si, i in spots:
        if made >= TARGET or time.time() - t0 > MAX_HOURS * 3600:
            break
        if (si, i) in done_ids:
            continue
        ctx = [{"role": m["role"], "content": m["content"]} for m in sessions[si][max(0, i - 12):i + 1]]
        while ctx and ctx[0]["role"] != "user":
            ctx.pop(0)
        previous = [m["content"] for m in ctx if m["role"] == "assistant"]
        try:
            a = reply(ctx, previous)
            b = reply(ctx, previous + [a], unlike=a, tries=5) if a else None
        except Exception as e:
            print(f"error: {e!r}", flush=True)
            if os.environ.get("FAIL_FAST"):
                raise
            time.sleep(30)
            continue
        if not a or not b or a == b:
            continue
        day = sessions[si][i].get("t", "")[:10]
        f.write(json.dumps({"id": 1000 + made, "chat": si, "turn": i,
                            "seed": {"topic": "your real chat", "mood": day},
                            "context": ctx, "a": a, "b": b}, ensure_ascii=False) + "\n")
        f.flush()
        made += 1
        if made % 10 == 0:
            print(f"{time.strftime('%H:%M')} {made}/{TARGET} real pairs, "
                  f"{(time.time() - t0) / 60:.0f} min", flush=True)
    print("== PAIRS DONE", made, flush=True)


if __name__ == "__main__":
    main_real() if os.environ.get("REAL") else main()
