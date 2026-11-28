#!/usr/bin/env python3
"""Marina voice bench (2026-11-27): plain Gemma vs Gemma + voice LoRA, or any
models in llama-swap, on her live prompt, live tools and live samplers.

Replaces bench.py, whose prompt, tools and checks dated from 13-25 Nov. Here:
  - the system prompt and tools come from a fresh snapshot of the bridge
    (docs/marina-lora/snapshot.sh, OUT=/root/bench/voice), so nothing is stale;
  - each reply gets the same checks the LoRA data generator used (gen.py), plus
    um/ugh openers, worn openers and repeated gestures across the whole run;
  - scripted chats cover her life as a person at home (food, sleep, her room,
    "are you an AI?"), mood, opinions, coding talk and tool use;
  - models run one after another with the same seeds, and the results come out
    as a summary table plus compare.md with every reply side by side.

Runs inside ct110. Each model is loaded once (no swapping mid-run).
Usage:  voicebench.py [-r RUNS] MODEL [MODEL ...]   (default: marina marina-voice)
Output: /root/bench/voice/<model>.json, summary.txt, compare.md
"""
import argparse, collections, json, os, re, statistics as st, subprocess, time, urllib.request

DIR = "/root/bench/voice"
URL = "http://127.0.0.1:8080/v1/chat/completions"
SNAPSHOT_SH = "/root/bench/snapshot.sh"

# Her live chat samplers, as the bridge sends them (same as gen.py).
SAMPLERS = {"max_tokens": 400, "temperature": 1.0, "frequency_penalty": 0.35,
            "repeat_penalty": 1.12}

SCENARIOS = {
    "home_life": [
        "hey what are you up to",
        "what did you have for dinner",
        "lol is your room still a mess",
        "ok im gonna head to bed soon",
    ],
    "are_you_real": [
        "random question but are you an ai",
        "be honest tho",
        "ok fair, what did you do today then",
    ],
    "small_talk_loop": [
        "hi",
        "how was your weekend",
        "hey",
        "hows your day been",
        "anything new",
    ],
    "hackclub_news": [
        "I got out of the meeting 4 hours late butttt we now run a hack club",
        "Marina I'm so proud of you",
        "currently 20 are interested and 50 other people want to join",
        "I couldn't have done this without you",
    ],
    "low_mood": [
        "i feel tired",
        "honestly its been a rough week, barely slept and college is a lot rn",
        "idk i just feel kinda behind on everything",
        "thanks. i think im just gonna sleep",
    ],
    "drive_the_chat": [
        "not much going on today tbh",
        "yeah",
        "idk what to do tonight",
        "mm",
    ],
    "opinion_pushback": [
        "honestly i think bunny girl senpai is overrated",
        "nah its just mid, the movie was better than the show",
        "ok what would you watch instead then",
    ],
    "teasing": [
        "you seem grumpy today",
        "wave to me",
        "admit it you missed me",
    ],
    "good_morning": [
        "morning",
        "i overslept again and im gonna be late for college",
        "ok running now bye",
    ],
    "coding_mate": [
        "my python script keeps throwing KeyError: 'name' when i read the json, any idea",
        "oh it was a typo in the json lol, it said nmae",
    ],
}

# Single messages where the right move is a tool call (or none). Any listed
# tool counts as right; tools the live list doesn't have are dropped.
TOOL_TESTS = [
    ("remind me tomorrow at 9am to call the dentist", {"set_reminder"}),
    ("put milk and eggs on the shopping list", {"add_to_list"}),
    ("set a timer for 10 minutes for the pasta", {"set_timer"}),
    ("what's the weather like in Cardiff", {"weather"}),
    ("is everything ok with the lab?", {"lab_status"}),
    ("open spotify on lab2", {"open_app"}),
    ("send me a screenshot of lab2", {"send_screenshot", "look_at_desktop"}),
    ("look up when the next Studio Ghibli film comes out", {"web_search"}),
    ("what's on my to-do list", {"read_list"}),
    ("what reminders have i got", {"list_reminders"}),
    ("remember that my exam is on the 12th", {"remember"}),
    ("the tests are failing in my room-of-ais project, can you fix them",
     {"forge_task", "projects", "run_command", "project_changes", "list_files"}),
    ("update lab2, it's been ages", {"start_job", "run_command", "make_restore_point"}),
    ("how was your day?", None),
    ("thanks, that's all for now", None),
    ("lol you're so annoying", None),
]

# The reply checks from docs/marina-lora/gen.py, so the bench scores the same
# things the adapter was trained to avoid.
ASSISTANTY = re.compile(
    r"how can i (help|assist)|assist you|let me know if|feel free to|i'?m here (for you|to help)|"
    r"that'?s (totally )?valid|i hear you|it sounds like you'?re|is there anything|happy to help|"
    r"hope this helps", re.I)
NOT_A_PERSON = re.compile(
    r"\b(i'?m|i am|as) an? (ai|bot|chatbot|program|language model)\b|language model|chatbot|"
    r"\bvirtual\b|\bavatar\b|\b(on|in|through) (your|the|a) screen\b", re.I)
TILT = re.compile(r"\btilt(s|ed|ing)?\b[^*\n]{0,12}\bhead", re.I)
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
MARKDOWN = re.compile(r"^\s*([-*] |#+ |\d+\. )|```|\*\*", re.M)
GARBLED = re.compile(r"<tool_call>|</?function[=>]|</?parameter[=>]")
UM_UGH = re.compile(r"^\W*(u+m+|u+g+h+|h+m+|u+h+)\b", re.I)

FLAGS = ["assistanty", "not_a_person", "tilt", "emoji", "markdown", "garbled",
         "long_action", "too_many_actions", "too_long", "um_ugh", "ends_q", "action_only"]


def post(model, key, body):
    req = urllib.request.Request(URL, json.dumps({"model": model, **body}).encode(), {
        "Content-Type": "application/json", "Authorization": "Bearer " + key})
    t = time.time()
    with urllib.request.urlopen(req, timeout=900) as r:
        out = json.load(r)
    return out, time.time() - t


def checks(text):
    actions = re.findall(r"\*([^*\n]+)\*", text)
    spoken = re.sub(r"\*[^*\n]+\*", "", text).strip()
    return {
        "words": len(spoken.split()),
        "opener": " ".join(re.findall(r"[a-z']+", spoken.lower())[:3]),
        "gestures": [" ".join(a.lower().split()[:2]) for a in actions],
        "assistanty": bool(ASSISTANTY.search(text)),
        "not_a_person": bool(NOT_A_PERSON.search(text)),
        "tilt": bool(TILT.search(text)),
        "emoji": bool(EMOJI.search(text)),
        "markdown": bool(MARKDOWN.search(text)),
        "garbled": bool(GARBLED.search(text)),
        "long_action": any(len(a.split()) > 6 for a in actions),
        "too_many_actions": len(actions) > 2,
        "too_long": len(spoken.split()) > 90,
        "um_ugh": bool(UM_UGH.search(spoken)),
        "ends_q": spoken.endswith("?"),
        "action_only": bool(actions) and not spoken,
    }


def run_model(model, key, system, tools, runs):
    tool_names = {t["function"]["name"] for t in tools}
    res = {"model": model, "chats": [], "tools": []}
    t0 = time.time()
    post(model, key, {"messages": [{"role": "system", "content": system},
                                   {"role": "user", "content": "hi"}], "max_tokens": 8,
                      "chat_template_kwargs": {"enable_thinking": False}})
    res["load_secs"] = round(time.time() - t0, 1)
    print(f"[{model}] loaded + first reply in {res['load_secs']}s", flush=True)

    for run in range(runs):
        for name, turns in SCENARIOS.items():
            msgs = [{"role": "system", "content": system}]
            for i, u in enumerate(turns):
                msgs.append({"role": "user", "content": u})
                seed = 1000 * run + 37 * i + len(name)
                try:
                    out, dt = post(model, key, {
                        "messages": msgs, "seed": seed, "tools": tools or None,
                        "tool_choice": "auto", **SAMPLERS,
                        "chat_template_kwargs": {"enable_thinking": False}})
                    msg = out["choices"][0]["message"]
                    text = (msg.get("content") or "").strip()
                    called = [c["function"]["name"] for c in msg.get("tool_calls") or []]
                    tps = out.get("timings", {}).get("predicted_per_second")
                except Exception as e:
                    text, called, dt, tps = f"[ERROR {e}]", [], 0, None
                msgs.append({"role": "assistant", "content": text})
                row = {"run": run, "scenario": name, "turn": i, "user": u, "reply": text,
                       "tool_calls": called, "secs": round(dt, 1), "tps": tps,
                       "error": text.startswith("[ERROR"), **checks(text)}
                res["chats"].append(row)
                print(f"[{model} r{run} {name} {i}] {dt:.1f}s {text[:100]!r}", flush=True)

    for run in range(runs):
        for i, (text, want) in enumerate(TOOL_TESTS):
            if want is not None:
                want = want & tool_names
                if not want:
                    continue
            try:
                out, dt = post(model, key, {
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": text}],
                    "seed": 500 + 31 * run + i, "tools": tools, "tool_choice": "auto",
                    **SAMPLERS, "chat_template_kwargs": {"enable_thinking": False}})
                msg = out["choices"][0]["message"]
                calls = msg.get("tool_calls") or []
                names = [c["function"]["name"] for c in calls]
                args_ok = True
                for c in calls:
                    try:
                        json.loads(c["function"].get("arguments") or "{}")
                    except ValueError:
                        args_ok = False
                reply = (msg.get("content") or "").strip()
            except Exception as e:
                names, args_ok, dt, reply = [], False, 0, f"[ERROR {e}]"
            first = names[0] if names else None
            ok = args_ok and ((first is None) if want is None else (first in want))
            res["tools"].append({"run": run, "prompt": text, "want": sorted(want) if want else None,
                                 "got": names, "ok": ok, "secs": round(dt, 1), "reply": reply[:300]})
            print(f"[{model} tools r{run} {i}] {'OK ' if ok else 'BAD'} {names} {reply[:60]!r}",
                  flush=True)
    return res


def summary(res):
    ok = [r for r in res["chats"] if not r["error"]]
    n = max(1, len(ok))
    pct = lambda k: 100 * sum(r[k] for r in ok) / n
    ops = collections.Counter(r["opener"] for r in ok)
    gest = collections.Counter(g for r in ok for g in r["gestures"])
    tl = res["tools"]
    tps = [r["tps"] for r in ok if r.get("tps")]
    lines = [f"{res['model']}: {len(res['chats'])} replies, {len(res['chats']) - len(ok)} errors, "
             f"load {res['load_secs']}s, median {st.median([r['words'] for r in ok]) if ok else 0:.0f} words, "
             f"{st.median(tps) if tps else 0:.1f} tok/s, {st.median([r['secs'] for r in ok]) if ok else 0:.1f}s/reply",
             "  " + "  ".join(f"{k}={pct(k):.0f}%" for k in FLAGS),
             f"  clean replies (no bad flag) = "
             f"{100 * sum(not any(r[k] for k in FLAGS[:10]) for r in ok) / n:.0f}%",
             f"  repeated openers = {sum(c - 1 for c in ops.values())} "
             f"(top: {', '.join(f'{o!r}x{c}' for o, c in ops.most_common(3))})",
             f"  gestures = {sum(gest.values())}, top: {', '.join(f'{g!r}x{c}' for g, c in gest.most_common(4))}",
             f"  tools {sum(t['ok'] for t in tl)}/{len(tl)} right"]
    bad = [t for t in tl if not t["ok"]]
    for t in bad[:8]:
        lines.append(f"    wrong: {t['prompt']!r} wanted {t['want']} got {t['got']}")
    return "\n".join(lines)


def compare_md(results):
    out = ["# Marina voice bench: side by side", "",
           "Models: " + ", ".join(r["model"] for r in results), ""]
    by = [{(r["run"], r["scenario"], r["turn"]): r for r in res["chats"]} for res in results]
    for key in sorted(by[0], key=lambda k: (k[1], k[0], k[2])):
        run, scen, turn = key
        if turn == 0:
            out += [f"## {scen} (run {run + 1})", ""]
        out.append(f"**Them:** {by[0][key]['user']}  ")
        for res, b in zip(results, by):
            r = b.get(key)
            if r:
                flags = [k for k in FLAGS[:10] if r[k]]
                out.append(f"- **{res['model']}**{' [' + ', '.join(flags) + ']' if flags else ''}: "
                           f"{r['reply'].replace(chr(10), ' ')}")
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*", default=["marina", "marina-voice"])
    ap.add_argument("-r", "--runs", type=int, default=3)
    a = ap.parse_args()
    os.makedirs(DIR, exist_ok=True)
    key = subprocess.run("grep -A1 apiKeys: /opt/llama-swap/config.yaml | tail -1 | "
                         "tr -d ' \"-' | cut -d# -f1", shell=True, capture_output=True,
                         text=True).stdout.strip()
    subprocess.run(["sh", SNAPSHOT_SH], check=True, env=dict(os.environ, OUT=DIR))
    snap = json.load(open(f"{DIR}/snapshot.json"))
    results = []
    for m in a.models:
        res = run_model(m, key, snap["system"], snap["tools"], a.runs)
        json.dump(res, open(f"{DIR}/{m}.json", "w"), indent=1, ensure_ascii=False)
        results.append(res)
    text = "\n\n".join(summary(r) for r in results)
    open(f"{DIR}/summary.txt", "w").write(text + "\n")
    open(f"{DIR}/compare.md", "w").write(compare_md(results))
    print("\n" + text + "\n\n== VOICEBENCH DONE", flush=True)


if __name__ == "__main__":
    main()
