#!/usr/bin/env bash
# Starts the Python bridge (ASR + LLM + GPT-SoVITS client).
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "No .venv here. Run ./setup-mac.sh first."
  exit 1
fi

# Call the interpreter directly — a moved project leaves stale absolute
# paths in activate and in every console-script shebang, but the
# interpreter itself resolves its prefix from its own location.
PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || { echo "No venv. Run ./setup-mac.sh" >&2; exit 1; }
exec "$PY" server/marina_server.py
