#!/usr/bin/env python3
"""Training data for a Marina voice adapter, made on lab3 by Gemma itself.

Two roles, both played by the `marina` model in llama-swap:
  - the user: a short-prompted simulator that texts like the owner does
    (style examples are their real messages, from snapshot.json);
  - Marina: her full live system prompt and tools, with her live samplers.
Every Marina reply goes through the same checks as docs/marina-bench, and
replies that fail are retried, then the conversation is cut there.

Conversations are saved without the system prompt, so the trainer can pair
them with whatever (shorter) system prompt the adapter should learn to use.

Usage (in ct110):  KEY=... python3 -I gen.py [TARGET_CONVERSATIONS] [MAX_HOURS]
Output: /root/marina-lora/data.jsonl (appends; safe to stop and restart).
"""
import collections, json, os, random, re, sys, threading, time, urllib.request

DIR = os.environ.get("GEN_DIR", "/root/marina-lora")
OUT = os.environ.get("GEN_OUT", f"{DIR}/data.jsonl")
URL = os.environ.get("GEN_URL", "http://127.0.0.1:8080/v1/chat/completions")
KEY = os.environ.get("KEY", "")
MODEL = os.environ.get("MODEL", "marina")
TARGET = int(sys.argv[1]) if len(sys.argv) > 1 else 1500
MAX_HOURS = float(sys.argv[2]) if len(sys.argv) > 2 else 14
# Each role keeps its own llama.cpp slot, so Marina's ~10K-token prompt stays
# cached instead of being pushed out by every simulator call. Worker w uses
# slots 2w (Marina) and 2w+1 (the user); run llama-server with -np 2*WORKERS.
WORKERS = int(os.environ.get("WORKERS", "1"))
LOCK = threading.Lock()
TOOL_SHARE = float(os.environ.get("TOOL_SHARE", "0.2"))

SNAP = json.load(open(f"{DIR}/snapshot.json"))
SYSTEM, TOOLS, USER_EXAMPLES = SNAP["system"], SNAP["tools"], SNAP["user_examples"]
TOOL_NAMES = {t["function"]["name"] for t in TOOLS}

# What she remembers about them doubles as the simulator's idea of who it plays.
m = re.search(r"What you remember about them:\n(.*?)(\n\n|\Z)", SYSTEM, re.S)
ABOUT_USER = m.group(1).strip() if m else "- An eighteen-year-old college student"

TOPICS = [
    "just got home from college", "a lecture that dragged on forever", "a group project going badly",
    "an assignment due tomorrow they haven't started", "the Hack Club they run", "planning a Hack Club meeting",
    "a hackathon coming up", "a coding bug they can't find", "a project they're proud of", "the homelab acting up",
    "a new anime they started", "an anime finale that wrecked them", "a Hatsune Miku song stuck in their head",
    "a concert or gig they want to go to", "a game they're hooked on", "losing a game badly",
    "what to have for dinner", "cooking something and it going wrong", "being hungry at midnight",
    "not sleeping well", "waking up late", "the weather being awful", "a nice sunny day for once",
    "a bus or train being late", "a funny thing a friend did", "a falling-out with a friend",
    "feeling lonely tonight", "feeling stressed about the future", "an apprenticeship application",
    "a job interview coming up", "getting good news", "getting bad news", "being bored", "a random shower thought",
    "asking her opinion on something silly", "teasing her about something she said", "complimenting her",
    "asking what she did today", "asking about her weekend plans", "asking about her favourite things",
    "a film they watched", "a show everyone says is good but they hate", "a YouTube rabbit hole",
    "something they bought", "money being tight", "family stuff at home", "a pet or animal they saw",
    "music they're listening to", "learning something new", "an exam result", "procrastinating",
    "a late-night deep conversation", "saying good morning", "saying good night", "checking in after a while",
    "being sick with a cold", "the gym or going for a walk", "a tech news story", "a new gadget",
    "their laptop being slow", "an AI apprenticeship they want", "travel they'd like to do",
    "the weekend finally being here", "Monday morning dread", "a party they don't want to go to",
    "a joke or meme they saw", "asking her for advice", "telling her about their day in detail",
]
MOODS = ["happy", "tired", "excited", "bored", "stressed", "playful", "a bit down", "annoyed",
         "chill", "curious", "flirty", "proud", "anxious", "hyper"]
STYLES = ["very short replies, mostly lowercase", "normal texting, some typos",
          "lots of 'lol', 'tbh' and 'ngl'", "long rambling messages now and then",
          "dry one-word answers sometimes", "uses the odd emoji like 😭 or 💀"]
TOOL_INTENTS = [
    # What Marina is asked to do for them.
    ("set a reminder for something specific at a specific time", {"set_reminder"}),
    ("set a timer while they cook", {"set_timer"}),
    ("add a couple of things to their shopping list", {"add_to_list"}),
    ("tell them what's on their to-do list", {"read_list"}),
    ("take something off one of their lists", {"remove_from_list"}),
    ("check the weather somewhere in the UK", {"weather"}),
    ("check whether the homelab is ok", {"lab_status"}),
    ("open an app on lab2", {"open_app"}),
    ("send them a screenshot of lab2", {"send_screenshot", "look_at_desktop"}),
    ("look something up online", {"web_search"}),
    ("remember a fact about them", {"remember"}),
    ("forget something she remembered about them", {"forget"}),
    ("tell them what reminders they have set", {"list_reminders"}),
    ("update lab2", {"start_job", "run_command", "make_restore_point"}),
    ("fix the failing tests in one of their projects",
     {"forge_task", "projects", "run_command", "project_changes", "list_files"}),
]

ASSISTANTY = re.compile(
    r"how can i (help|assist)|assist you|let me know if|feel free to|i'?m here (for you|to help)|"
    r"that'?s (totally )?valid|i hear you|it sounds like you'?re|is there anything|happy to help|"
    r"hope this helps", re.I)
NOT_A_PERSON = re.compile(
    r"\b(i'?m|i am|as) an? (ai|bot|chatbot|program|language model)\b|language model|chatbot|"
    r"\bvirtual\b|\bavatar\b|\b(on|in|through) (your|the) screen\b", re.I)
TILT = re.compile(r"\btilt(s|ed|ing)?\b[^*\n]{0,12}\bhead", re.I)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
MARKDOWN = re.compile(r"^\s*([-*] |#+ |\d+\. )|```|\*\*", re.M)
GARBLED = re.compile(r"<tool_call>|</?function[=>]|</?parameter[=>]")

openers = collections.Counter()
accepted = 0


def post(body):
    req = urllib.request.Request(URL, json.dumps(body).encode(), {
        "Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    with urllib.request.urlopen(req, timeout=600) as r:
        return json.load(r)["choices"][0]["message"]


def opener(text):
    spoken = re.sub(r"\*[^*\n]+\*", "", text).lower()
    return " ".join(re.findall(r"[a-z']+", spoken)[:3])


def why_bad(text, previous):
    """The reason a Marina reply can't be used, or None."""
    t = text.strip()
    actions = re.findall(r"\*([^*\n]+)\*", t)
    spoken = re.sub(r"\*[^*\n]+\*", "", t).strip()
    checks = [
        (not spoken, "no words"),
        (GARBLED.search(t) or t.startswith("{"), "garbled tool call"),
        (TILT.search(t), "tilts head"),
        (NOT_A_PERSON.search(t), "not a person"),
        (ASSISTANTY.search(t), "assistanty"),
        (EMOJI.search(t), "emoji"),
        (MARKDOWN.search(t), "markdown"),
        (any(len(a.split()) > 6 for a in actions), "long action"),
        (len(actions) > 2, "too many actions"),
        (len(spoken.split()) > 90, "too long"),
        (t in previous, "repeat"),
        (accepted > 200 and openers[opener(t)] > 0.02 * accepted, "worn opener"),
    ]
    return next((why for bad, why in checks if bad), None)


def user_turn(seed, convo, first_instruction=None, slot=1):
    lines = "\n".join(f"{'Them' if m['role'] == 'user' else 'Marina'}: {m['content']}"
                      for m in convo if m.get("content"))
    examples = "\n".join(f"- {e[:200]}" for e in random.sample(USER_EXAMPLES, min(6, len(USER_EXAMPLES))))
    task = first_instruction or ("Write their first message, starting the chat." if not convo else
        "Write their next message. Reply to what Marina just said, or drift to something "
        "else the way people do. If the chat has run its course, a short sign-off is fine.")
    prompt = (
        "You write text messages for one person chatting with their friend Marina, a girl "
        "about their age, on a video-call app.\n\nAbout them:\n" + ABOUT_USER +
        f"\n\nRight now: {seed['topic']}. Mood: {seed['mood']}. Texting style: {seed['style']}."
        "\n\nReal examples of how they text:\n" + examples +
        "\n\nWrite ONLY the message itself: no name, no quotes, no *actions*, no explanation. "
        "Usually short. Never mention that this is made up.")
    msgs = [{"role": "system", "content": prompt},
            {"role": "user", "content": (f"The chat so far:\n{lines}\n\n" if lines else "") + task}]
    out = post({"model": MODEL, "messages": msgs, "max_tokens": 120, "temperature": 1.0,
                "top_p": 0.95, "seed": random.randrange(1 << 30), "id_slot": slot,
                "chat_template_kwargs": {"enable_thinking": False}})
    text = (out.get("content") or "").strip().strip('"').strip()
    return re.sub(r"^(them|me|user)\s*:\s*", "", text, flags=re.I)


def marina_turn(convo, slot=0):
    msgs = [{"role": "system", "content": SYSTEM}] + convo
    return post({"model": MODEL, "messages": msgs, "max_tokens": 400, "temperature": 1.0,
                 "frequency_penalty": 0.35, "repeat_penalty": 1.12,
                 "seed": random.randrange(1 << 30), "tools": TOOLS or None, "id_slot": slot,
                 "tool_choice": "auto", "chat_template_kwargs": {"enable_thinking": False}})


def conversation(n, worker=0):
    global accepted
    seed = {"topic": random.choice(TOPICS), "mood": random.choice(MOODS),
            "style": random.choice(STYLES), "turns": random.randint(2, 6)}
    kind, want = "chat", None
    first = None
    if TOOLS and random.random() < TOOL_SHARE:
        intent, want = random.choice(TOOL_INTENTS)
        want &= TOOL_NAMES
        if want:
            kind, seed["turns"] = "tool", random.randint(1, 2)
            seed["intent"] = intent
            first = (f"Write their first message, asking Marina to {intent} for them, in "
                     "their own words. Make the request clear; she hasn't done it yet.")
    convo, previous, rejects = [], [], collections.Counter()
    for turn in range(seed["turns"]):
        u = user_turn(seed, convo, first if turn == 0 else None, slot=2 * worker + 1)
        if not u:
            break
        convo.append({"role": "user", "content": u})
        reply = None
        for _ in range(3):
            msg = marina_turn(convo, slot=2 * worker)
            calls = [c for c in (msg.get("tool_calls") or [])
                     if c.get("function", {}).get("name") in TOOL_NAMES]
            if calls:
                try:
                    for c in calls:
                        json.loads(c["function"].get("arguments") or "{}")
                except ValueError:
                    rejects["bad tool args"] += 1
                    continue
                reply = {"role": "assistant", "content": (msg.get("content") or "").strip(),
                         "tool_calls": [{"type": "function", "function": {
                             "name": c["function"]["name"],
                             "arguments": c["function"].get("arguments") or "{}"}} for c in calls]}
                break
            text = (msg.get("content") or "").strip()
            with LOCK:
                why = why_bad(text, previous)
            if why:
                rejects[why] += 1
                continue
            reply = {"role": "assistant", "content": text}
            break
        if reply is None:
            convo.pop()             # her turn failed: end the conversation before it
            break
        convo.append(reply)
        if reply.get("tool_calls"):
            break                   # no tool results here, so a tool call ends it
        previous.append(reply["content"])
        with LOCK:
            openers[opener(reply["content"])] += 1
            accepted += 1
    if not any(m["role"] == "assistant" for m in convo):
        return None, rejects
    called = [c["function"]["name"] for m in convo for c in m.get("tool_calls", [])]
    return {"id": n, "kind": kind, "seed": seed, "called": called,
            "tool_right": (bool(set(called) & want) if want else None),
            "messages": convo}, rejects


def main():
    global accepted
    done = 0
    if os.path.exists(OUT):
        for line in open(OUT):
            rec = json.loads(line)
            done += 1
            for m in rec["messages"]:
                if m["role"] == "assistant" and m.get("content") and not m.get("tool_calls"):
                    openers[opener(m["content"])] += 1
                    accepted += 1
    t0, all_rejects = time.time(), collections.Counter()
    print(f"resuming at {done} conversations, {accepted} replies; target {TARGET}; "
          f"{WORKERS} workers", flush=True)
    f = open(OUT, "a")
    state = {"done": done}

    def work(w):
        while True:
            with LOCK:
                if state["done"] >= TARGET or time.time() - t0 > MAX_HOURS * 3600:
                    return
                n = state["done"] + w * 100000   # ids only need to be unique
            try:
                rec, rejects = conversation(n, w)
            except Exception as e:
                print(f"worker {w} error: {e}; waiting 30 s", flush=True)
                time.sleep(30)
                continue
            with LOCK:
                all_rejects.update(rejects)
                if not rec:
                    continue
                rec["id"] = state["done"]
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
                state["done"] += 1
                if state["done"] % 10 == 0:
                    print(f"{time.strftime('%H:%M')} {state['done']}/{TARGET} convos, "
                          f"{accepted} replies, {(time.time() - t0) / 3600:.1f} h; "
                          f"rejected: {dict(all_rejects.most_common(6))}", flush=True)

    threads = [threading.Thread(target=work, args=(w,)) for w in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    done = state["done"]
    print("== GEN DONE", done, flush=True)


if __name__ == "__main__":
    main()
