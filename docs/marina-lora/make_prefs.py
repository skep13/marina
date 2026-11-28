#!/usr/bin/env python3
"""The owner's picks + the pairs they judged -> prefs.jsonl for modal_train's dpo.

  python3 make_prefs.py pairs.jsonl PICKS_DIR > prefs.jsonl

PICKS_DIR holds the picker page's `picks` documents as JSON files (one per
pair, {"id", "pick": "a"|"b"|"close"|"bad", ...}), as ArtifactData saves them
with out_dir. "close" and "bad" picks are left out: they say nothing about
which reply is better.
"""
import collections, glob, json, os, sys

pairs = {}
for line in open(sys.argv[1]):
    if line.strip():
        p = json.loads(line)
        pairs[p["id"]] = p
picks = {}
for f in glob.glob(os.path.join(sys.argv[2], "**", "*.json"), recursive=True):
    d = json.load(open(f))
    d = d.get("data", d)                     # tolerate a {"data": {...}} wrapper
    if "id" in d and "pick" in d:
        picks[int(d["id"])] = d["pick"]

n = collections.Counter()
for pid, pick in sorted(picks.items()):
    p = pairs.get(pid)
    if not p:
        n["pair missing"] += 1
        continue
    if pick not in ("a", "b"):
        n[pick] += 1
        continue
    other = "b" if pick == "a" else "a"
    print(json.dumps({"id": pid, "context": p["context"], "chosen": p[pick],
                      "rejected": p[other]}, ensure_ascii=False))
    n["used"] += 1
print(f"{len(picks)} picks: {dict(n)}", file=sys.stderr)
