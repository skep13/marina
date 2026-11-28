#!/bin/sh
# Save Marina's live system prompt, tool definitions and a few of the owner's
# real messages (texting-style examples for the simulated user) into
# /root/marina-lora, the way the bridge builds them right now. Run in ct110.
set -e
OUT=${OUT:-/root/marina-lora}
mkdir -p "$OUT"
cd /opt/marina
runuser -u marina -- env MARINA_ROOT=/opt/marina MARINA_DATA=/var/lib/marina \
  HOME=/var/lib/marina /opt/marina/.venv/bin/python - > "$OUT/snapshot.json" <<'EOF'
import json, sys
sys.path.insert(0, "server")
from process.llm_funcs import llm_scr
from process.tools import registry
from process.config import resolve_data
hist = json.load(open(resolve_data("chat_history.json")))
users = [m["content"] for m in hist
         if m.get("role") == "user" and isinstance(m.get("content"), str)]
json.dump({"system": llm_scr.system_message()["content"],
           "tools": registry.definitions() or [],
           "user_examples": users[-40:]}, sys.stdout, ensure_ascii=False)
EOF
python3 -I -c "import json; d=json.load(open('$OUT/snapshot.json')); \
print('system', len(d['system']), 'chars;', len(d['tools']), 'tools;', len(d['user_examples']), 'user examples')"
