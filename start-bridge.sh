#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "No .venv here. Run ./setup-mac.sh first."
  exit 1
fi

PY="$(pwd)/.venv/bin/python"
[ -x "$PY" ] || { echo "No venv. Run ./setup-mac.sh" >&2; exit 1; }
exec "$PY" server/marina_server.py
