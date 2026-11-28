#!/usr/bin/env python3
"""All the owner's picks with their pairs -> picked.jsonl (context, chosen, rejected, src)."""
import glob, json, sys
pairs = {}
for f in ("pairs.jsonl", "pairs-real.jsonl", "pairs-v2.jsonl"):
    for l in open(f):
        if l.strip():
            p = json.loads(l); pairs[p["id"]] = p
n = {"close": 0, "bad": 0, "missing": 0}
out = open("picked.jsonl", "w")
for f in sorted(glob.glob("picks/picks/*.json")):
    d = json.load(open(f)); d = d.get("data", d)
    p = pairs.get(d["id"])
    if not p: n["missing"] += 1; continue
    if d["pick"] not in ("a", "b"): n[d["pick"]] += 1; continue
    o = "b" if d["pick"] == "a" else "a"
    src = "sim1" if d["id"] < 1000 else "real" if d["id"] < 2000 else "sim2"
    out.write(json.dumps({"id": d["id"], "src": src, "context": p["context"], "chosen": p[d["pick"]],
                          "rejected": p[o], "chosen_side": d["pick"]}, ensure_ascii=False) + "\n")
print(n, file=sys.stderr)
