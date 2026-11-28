#!/usr/bin/env python3
"""The owner's real Telegram chats with Marina, from the bridge's journal.

The bridge logs each message as "[telegram] you: ..." / "[telegram] marina: ..."
(her multi-line replies go on in unprefixed lines). This splits them into
sessions at gaps over 45 minutes and writes them as chat messages, so
pairgen.py can ask for two replies at the owner's own messages instead of
simulated ones.

Usage (in ct110):  python3 -I real_chats.py > /root/marina-lora/real_chats.json
"""
import datetime, json, re, subprocess

GAP = datetime.timedelta(minutes=45)
LINE = re.compile(r"^(\S+) \S+ \S+: (.*)$")          # short-iso: time host unit: text
MSG = re.compile(r"^\[(telegram|speaker)\] (you|marina): ?(.*)$")
TAG = re.compile(r"^\[[a-z_ -]+\] ")                  # any other bridge log line

out = subprocess.run(["journalctl", "-u", "marina", "--no-pager", "-o", "short-iso"],
                     capture_output=True, text=True).stdout.splitlines()
sessions, cur, last_t, open_msg = [], [], None, None
for raw in out:
    m = LINE.match(raw)
    if not m:
        continue
    try:
        t = datetime.datetime.fromisoformat(m.group(1))
    except ValueError:
        continue
    text = m.group(2)
    mm = MSG.match(text)
    if mm:
        if last_t and t - last_t > GAP and cur:
            sessions.append(cur); cur = []
        last_t = t
        role = "user" if mm.group(2) == "you" else "assistant"
        open_msg = {"role": role, "content": mm.group(3), "t": t.isoformat()}
        cur.append(open_msg)
    elif TAG.match(text) or text.startswith(("Started ", "Stopped ", "INFO", "WARNING")):
        open_msg = None                                # her reply ended; a log line follows
    elif open_msg is not None and open_msg["role"] == "assistant":
        open_msg["content"] += "\n" + text
if cur:
    sessions.append(cur)

# Merge back-to-back messages from the same side (she often sends two bubbles).
clean = []
for s in sessions:
    merged = []
    for m in s:
        m["content"] = m["content"].strip()
        if not m["content"]:
            continue
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1]["content"] += "\n" + m["content"]
        else:
            merged.append(m)
    if any(m["role"] == "user" for m in merged):
        clean.append(merged)
json.dump(clean, __import__("sys").stdout, ensure_ascii=False, indent=0)
n = sum(m["role"] == "user" for s in clean for m in s)
print(f"{len(clean)} sessions, {n} owner messages", file=__import__("sys").stderr)
