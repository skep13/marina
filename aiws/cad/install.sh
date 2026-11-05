#!/usr/bin/env bash
# Install the `cad` command (text -> build123d -> STEP for Onshape) for this user.
# Needs uv. build123d's OpenCascade wheels lag new Pythons, so the venv uses 3.12.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)"
HOME_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/aiws/cad"
BIN="$HOME/.local/bin"
mkdir -p "$HOME_DIR" "$BIN"

if [ ! -x "$HOME_DIR/venv/bin/python" ]; then
  uv venv --python 3.12 "$HOME_DIR/venv"
fi
uv pip install --python "$HOME_DIR/venv/bin/python" -q build123d
install -m 644 "$SRC/cad.py" "$HOME_DIR/cad.py"

cat > "$BIN/cad" <<EOF
#!/bin/sh
exec "$HOME_DIR/venv/bin/python" "$HOME_DIR/cad.py" "\$@"
EOF
chmod 755 "$BIN/cad"
echo "installed: $BIN/cad  (try: cad --help)"
