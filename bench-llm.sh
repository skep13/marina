#!/usr/bin/env bash
# Benchmarks any Ollama / llama.cpp / LM Studio endpoint so you can compare
# machines honestly instead of guessing.
#
#   ./bench-llm.sh                                  # whatever the config points at
#   ./bench-llm.sh http://thinkpad.local:11434 llama3.2:3b
#   ./bench-llm.sh http://beelink.local:11434 qwen3:8b
set -euo pipefail
cd "$(dirname "$0")"
# Call the interpreter directly — a moved project leaves stale absolute
# paths in activate and in every console-script shebang, but the
# interpreter itself resolves its prefix from its own location.
PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || { echo "No venv. Run ./setup-mac.sh" >&2; exit 1; }

HOST="${1:-}"
MODEL="${2:-}"

HOST="$HOST" MODEL="$MODEL" "$PY" - <<'PY'
import json, os, sys, time, urllib.request, yaml
from pathlib import Path

cfg = yaml.safe_load(Path("character_config.yaml").read_text())
base = os.environ.get("HOST") or (cfg["llm"].get("base_url") or "").rstrip("/")
model = os.environ.get("MODEL") or cfg["llm"]["model"]
if not base:
    sys.exit("No endpoint. Pass one, or set llm.base_url in character_config.yaml")
base = base.removesuffix("/v1")

def call(prompt, n_predict=120):
    body = json.dumps({"model": model, "prompt": prompt, "stream": False,
                       "options": {"num_predict": n_predict}}).encode()
    req = urllib.request.Request(f"{base}/api/generate", body,
                                 {"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.load(r)
    return d, time.time() - t0

print(f"endpoint : {base}")
print(f"model    : {model}\n")

# A long prompt exposes prefill speed, which is what actually decides how long
# you wait before she starts talking.
long_prompt = ("You are a helpful assistant. " + "Context sentence. " * 120
               + "\n\nQuestion: name three colours.")

for label, prompt, n in [("short prompt", "Say hello.", 60),
                         ("long prompt (~900 tok)", long_prompt, 60)]:
    try:
        d, wall = call(prompt, n)
    except Exception as e:
        print(f"{label:<24} FAILED: {e}")
        continue
    pe, ped = d.get("prompt_eval_count", 0), d.get("prompt_eval_duration", 0) / 1e9
    ec, ed = d.get("eval_count", 0), d.get("eval_duration", 0) / 1e9
    print(f"{label}")
    print(f"  prefill  : {pe:>5} tok in {ped:6.2f}s  = {pe/max(ped,1e-6):7.1f} tok/s")
    print(f"  generate : {ec:>5} tok in {ed:6.2f}s  = {ec/max(ed,1e-6):7.1f} tok/s")
    print(f"  wall     : {wall:.2f}s\n")

print("Rule of thumb: under ~2s to first word feels conversational.")
print("Prefill matters most — it is what you wait through before she speaks.")
PY
