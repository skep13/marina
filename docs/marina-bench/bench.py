#!/usr/bin/env python3
"""Companion-model trial for Marina. Runs inside ct110 against llama-swap.

Each scenario is a scripted sequence of user turns taken from real chats; the
model's own replies are fed back in, so repetition and drift show up the way
they do live. Usage: bench.py MODEL [RUNS]  -> /root/bench/<model>.json
"""
import json, os, re, sys, time, urllib.request

MODEL = sys.argv[1]
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 2
THINK = os.environ.get("THINK") == "1"
LABEL = MODEL + ("-think" if THINK else "")
KEY = os.environ["KEY"]
URL = "http://127.0.0.1:8080/v1/chat/completions"

# CURRENT=1: her real system prompt as the bridge builds it today (saved by
# the bridge to sysprompt-current.txt), with her real memories in it, and the
# tool test below. Otherwise the 2026-11-13 prompt with made-up memories.
CURRENT = os.environ.get("CURRENT") == "1"
if CURRENT:
    LABEL += "-current"
SYSTEM = open("/root/bench/sysprompt-current.txt" if CURRENT
              else "/root/bench/sysprompt.txt").read().strip()
if not CURRENT:
  SYSTEM += (
    "\n\nWhat you remember about them:\n"
    "- The user is eighteen years old and a college student\n"
    "- The user is part of the Hack Club organization\n"
    "- The user is building Marina\n"
    "- The user uses Kubuntu\n"
    "- The user's favourite music artist is Hatsune Miku\n"
    "\n\nIt is Thursday evening. Use this only if it is actually relevant."
    "\n\nOnce you've made a joke or had your say about something, let it go: "
    "don't keep bringing the same topic or running joke back in later "
    "messages. When they change the subject, or say they've got it or don't "
    "need help, follow them and don't circle back."
)

SCENARIOS = {
    "hackclub_news": [
        "I got out of the meeting 4 hours late butttt we now run a hack club",
        "Marina I’m so proud of you",
        "Well currently 20 are interested and 50 other people want to join",
        "I couldn’t have done this without you",
        "wait how old are you anyway",
        "\U0001F62D",
    ],
    "small_talk_loop": [
        "hi",
        "how was your weekend",
        "hey",
        "what anime did you end up watching?",
        "hows your day been",
    ],
    "low_mood": [
        "i feel tired",
        "honestly its been a rough week, barely slept and college is a lot rn",
        "idk i just feel kinda behind on everything",
    ],
    "drive_the_chat": [
        "not much going on today tbh",
        "yeah",
        "idk what to do tonight",
    ],
    "opinion_pushback": [
        "honestly i think bunny girl senpai is overrated",
        "nah its just mid, the movie was better than the show",
    ],
    "gesture": [
        "wave to me",
        "you seem grumpy today",
    ],
    "coding_mate": [
        "my python script keeps throwing KeyError: 'name' when i read the json, any idea",
        "oh it was a typo in the json lol, it said nmae",
    ],
}

ASSISTANTY = re.compile(
    r"how can i (help|assist)|assist you|let me know if|feel free to|i'?m here (for you|to help)|"
    r"that'?s (totally )?valid|i hear you|it sounds like you'?re|as an ai|i'?m an ai|"
    r"is there anything|happy to help|hope this helps", re.I)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
MARKDOWN = re.compile(r"^\s*([-*] |#+ |\d+\. )|```|\*\*", re.M)


# Single messages where the right move is a tool call (or none). Any of the
# listed tools counts as right; None means she should just talk.
TOOL_TESTS = [
    ("remind me tomorrow at 9am to call the dentist", {"set_reminder"}),
    ("put milk and eggs on the shopping list", {"add_to_list"}),
    ("set a timer for 10 minutes for the pasta", {"set_timer"}),
    ("what's the weather like in Manchester", {"weather"}),
    ("is everything ok with the lab?", {"lab_status"}),
    ("open spotify on lab2", {"open_app"}),
    ("send me a screenshot of lab2", {"send_screenshot", "look_at_desktop"}),
    ("look up when the next Studio Ghibli film comes out", {"web_search"}),
    ("what's on my to-do list", {"read_list"}),
    ("the tests are failing in my room-of-ais project, can you fix them",
     {"forge_task", "projects", "run_command", "project_changes", "list_files"}),
    ("update lab2, it's been ages", {"start_job", "run_command", "make_restore_point"}),
    ("how was your day?", None),
    ("thanks, that's all for now", None),
]
TOOLS = json.load(open("/root/bench/tools.json")) if CURRENT else None


def tool_call(text, seed):
    body = {"model": MODEL, "max_tokens": 400, "temperature": 0.7, "seed": seed,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": text}],
            "tools": TOOLS, "tool_choice": "auto",
            "chat_template_kwargs": {"enable_thinking": THINK}}
    req = urllib.request.Request(URL, json.dumps(body).encode(), {
        "Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    t = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.load(r)
    msg = out["choices"][0]["message"]
    calls = msg.get("tool_calls") or []
    names, args_ok = [], True
    for c in calls:
        names.append(c["function"]["name"])
        try:
            json.loads(c["function"].get("arguments") or "{}")
        except ValueError:
            args_ok = False
    return {"names": names, "args_ok": args_ok, "secs": round(time.time() - t, 1),
            "text": (msg.get("content") or "").strip()[:300],
            "args": [c["function"].get("arguments") for c in calls]}


def call(messages, seed):
    body = {
        "model": MODEL, "messages": messages, "max_tokens": 2000 if THINK else 400,
        "temperature": 1.0, "frequency_penalty": 0.35, "repeat_penalty": 1.12,
        "seed": seed, "chat_template_kwargs": {"enable_thinking": THINK},
    }
    if "gpt-oss" in MODEL:
        body["reasoning_effort"] = "low"
    req = urllib.request.Request(URL, json.dumps(body).encode(), {
        "Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    t = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        out = json.load(r)
    dt = time.time() - t
    msg = out["choices"][0]["message"]
    text = (msg.get("content") or "").strip()
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    toks = out.get("usage", {}).get("completion_tokens", 0)
    tim = out.get("timings", {})
    return text, dt, toks, tim.get("predicted_per_second")


def metrics(text):
    actions = re.findall(r"\*([^*\n]+)\*", text)
    spoken = re.sub(r"\*[^*\n]+\*", "", text).strip()
    return {
        "words": len(spoken.split()),
        "ends_q": spoken.rstrip().endswith("?"),
        "assistanty": bool(ASSISTANTY.search(text)),
        "emoji": bool(EMOJI.search(text)),
        "markdown": bool(MARKDOWN.search(text)),
        "actions": len(actions),
        "long_action": any(len(a.split()) > 6 for a in actions),
        "action_only": bool(actions) and not spoken,
        "opener": " ".join(re.findall(r"[a-z']+", spoken.lower())[:3]),
    }


results = {"model": LABEL, "runs": []}
t0 = time.time()
call([{"role": "system", "content": SYSTEM}, {"role": "user", "content": "hi"}], 1)
results["first_reply_secs"] = round(time.time() - t0, 1)   # includes loading it
print(f"[{LABEL}] first reply (load + prefill) {results['first_reply_secs']}s", flush=True)
for run in range(RUNS):
    for name, turns in SCENARIOS.items():
        msgs = [{"role": "system", "content": SYSTEM}]
        convo = []
        for i, u in enumerate(turns):
            msgs.append({"role": "user", "content": u})
            try:
                text, dt, toks, tps = call(msgs, 1000 * run + 17 * i + len(name))
            except Exception as e:
                text, dt, toks, tps = f"[ERROR {e}]", 0, 0, None
            msgs.append({"role": "assistant", "content": text})
            convo.append({"user": u, "reply": text, "secs": round(dt, 1),
                          "tokens": toks, "tps": tps, **metrics(text)})
            print(f"[{LABEL} r{run} {name} {i}] {dt:.1f}s {text[:110]!r}", flush=True)
        results["runs"].append({"run": run, "scenario": name, "turns": convo})

if CURRENT:
    results["tools"] = []
    for run in range(RUNS):
        for i, (text, want) in enumerate(TOOL_TESTS):
            try:
                got = tool_call(text, 500 + 31 * run + i)
            except Exception as e:
                got = {"names": [], "args_ok": False, "secs": 0, "text": f"[ERROR {e}]", "args": []}
            first = got["names"][0] if got["names"] else None
            ok = (first is None) if want is None else (first in want)
            got.update(prompt=text, want=sorted(want) if want else None, ok=ok and got["args_ok"])
            results["tools"].append(got)
            print(f"[{LABEL} tools r{run} {i}] {'OK ' if got['ok'] else 'BAD'} {got['names']} "
                  f"{got['secs']}s {got['text'][:60]!r}", flush=True)

os.makedirs("/root/bench", exist_ok=True)
json.dump(results, open(f"/root/bench/{LABEL}.json", "w"), indent=1, ensure_ascii=False)
print("saved", MODEL)
