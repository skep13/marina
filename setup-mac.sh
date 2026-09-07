#!/usr/bin/env bash
# One-time setup for the Mac side.
#
# The Mac runs: microphone -> Faster-Whisper -> (your LLM) -> Kokoro TTS -> avatar.
# Nothing here needs torch, CUDA, or GPT-SoVITS.
set -euo pipefail
cd "$(dirname "$0")"

# ----------------------------------------------------------------------
# Find a Python >= 3.10.
#
# macOS ships 3.9, and onnxruntime >= 1.20 (which Kokoro needs) has no 3.9
# wheels. Rather than touch the system Python, fall back to uv, which installs
# a standalone interpreter under ~/.local/share/uv.
# ----------------------------------------------------------------------

is_ok() {
  [ -x "$1" ] && "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)' 2>/dev/null
}

PY="${PYTHON:-}"

if [ -n "$PY" ] && ! is_ok "$PY"; then
  echo "PYTHON=$PY is older than 3.10; ignoring it." >&2
  PY=""
fi

if [ -z "$PY" ]; then
  for c in "$HOME/.local/bin/python3.12" python3.12 python3.13 python3.11 python3; do
    resolved="$(command -v "$c" 2>/dev/null || true)"
    if [ -n "$resolved" ] && is_ok "$resolved"; then PY="$resolved"; break; fi
  done
fi

if [ -z "$PY" ]; then
  echo "==> No Python 3.10+ found; installing one with uv"
  UV="$(command -v uv || true)"
  if [ -z "$UV" ]; then
    python3 -m pip install --quiet --user uv
    UV="$(python3 -c 'import site,os;print(os.path.join(site.USER_BASE,"bin","uv"))')"
  fi
  "$UV" python install 3.12
  PY="$("$UV" python find 3.12)"
fi

if [ -z "$PY" ] || ! is_ok "$PY"; then
  echo "Could not find or install Python 3.10+. Set PYTHON=/path/to/python3.12 and retry." >&2
  exit 1
fi

echo "Using $("$PY" --version) at $PY"

# Only now is it safe to destroy the old environment.
echo "==> Creating .venv"
rm -rf .venv
"$PY" -m venv .venv
source .venv/bin/activate
python -m pip install --quiet --upgrade pip wheel

echo "==> Installing Python dependencies (~500 MB the first time)"
pip install -r server/requirements-mac.txt

echo "==> Fetching the Kokoro voice model (~340 MB)"
./download-kokoro.sh

echo "==> Installing desktop app dependencies"
( cd app && npm install )

echo "==> Building the renderer vendor bundle (three.js + three-vrm)"
( cd app && npx esbuild src/vendor-entry.js --bundle --format=esm \
    --outfile=renderer/vendor/vrm-bundle.js --log-level=warning )

cat <<'DONE'

Done. Next:
  1. Point llm.base_url at your server in character_config.yaml
  2. Drop your exported model at app/models/model.vrm
  3. ./start-bridge.sh     (terminal 1)
  4. ./start-app.sh        (terminal 2)
DONE
