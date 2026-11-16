#!/bin/bash
# Install the AI workstation for the current user only: no sudo, no system
# packages. For machines where sudo isn't available yet; the system-level
# extras (tmux, wtype, ydotool, tailscale, CUDA llama.cpp) are listed at the end.
#
#   install-user.sh SRC_TREE      (the aiws/ folder, already copied here)
#
# Layout:
#   ~/.local/share/aiws/{src,orb,venv,electron}   code and runtimes
#   ~/.config/aiws/etc/{aiws.yaml,models.d,secrets.env}
#   ~/.local/state/aiws/                           tokens, database, logs
#   ~/.config/systemd/user/{aiwsd,aiws-agent}.service
#   ~/.local/bin/{ai,aiws-orb,aiws-control,aiws-agent-stop}
set -euo pipefail
SRC=$(cd "${1:?usage: install-user.sh path/to/aiws}" && pwd)
SHARE=$HOME/.local/share/aiws
ETC=$HOME/.config/aiws/etc
STATE=$HOME/.local/state/aiws
BIN=$HOME/.local/bin
ELECTRON_VERSION=44.2.0
say() { printf '\n== %s\n' "$*"; }

say "code"
mkdir -p "$SHARE" "$ETC/models.d" "$ETC/workers.d" "$STATE" "$BIN" "$HOME/.config/systemd/user"
rsync -a --delete --exclude __pycache__ "$SRC/src/" "$SHARE/src/"
rsync -a --delete "$SRC/orb/" "$SHARE/orb/"
install -m 755 "$SRC/tools/ai-bench" "$SRC/tools/ai-mem" "$BIN/"

say "python environment (fastapi, uvicorn, httpx, pyyaml)"
[ -x "$SHARE/venv/bin/python" ] || python3 -m venv "$SHARE/venv"
"$SHARE/venv/bin/pip" install -q --upgrade pip
"$SHARE/venv/bin/pip" install -q fastapi uvicorn httpx pyyaml

say "electron $ELECTRON_VERSION (for Marina's sphere)"
if [ ! -x "$SHARE/electron/electron" ]; then
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/e.zip" \
    "https://github.com/electron/electron/releases/download/v$ELECTRON_VERSION/electron-v$ELECTRON_VERSION-linux-x64.zip"
  mkdir -p "$SHARE/electron" && (cd "$SHARE/electron" && python3 -m zipfile -e "$tmp/e.zip" . && chmod +x electron chrome_crashpad_handler 2>/dev/null; true)
  chmod 4755 "$SHARE/electron/chrome-sandbox" 2>/dev/null || true
  rm -rf "$tmp"
fi

say "settings"
[ -f "$ETC/aiws.yaml" ] || cp "$SRC/laptop/etc/aiws/aiws.yaml" "$ETC/aiws.yaml"
cp -n "$SRC/laptop/etc/aiws/models.d/"*.yaml "$ETC/models.d/" 2>/dev/null || true
touch "$ETC/secrets.env" && chmod 600 "$ETC/secrets.env"

ENV="AIWS_ETC=$ETC AIWS_STATE=$STATE AIWS_MODELS=$STATE/models AIWS_LLAMA_SWAP_CONFIG=$STATE/llama-swap.yaml PYTHONPATH=$SHARE/src"

say "user services"
cat > "$HOME/.config/systemd/user/aiwsd.service" <<EOF
[Unit]
Description=AI workstation gateway (aiwsd), user install
After=network-online.target

[Service]
Environment=$ENV
ExecStart=$SHARE/venv/bin/python -m aiws.server
Restart=on-failure

[Install]
WantedBy=default.target
EOF
cat > "$HOME/.config/systemd/user/aiws-agent.service" <<EOF
[Unit]
Description=AI workstation assistant, user install
After=aiwsd.service

[Service]
Environment=$ENV AIWS_TOKEN_FILE=$STATE/desktop.token
ExecStart=$SHARE/venv/bin/python -m aiws.agent.loop
Restart=always
RestartSec=2
NoNewPrivileges=yes
KillMode=control-group
EOF

say "commands"
cat > "$BIN/ai" <<EOF
#!/bin/sh
export $ENV AIWS_TOKEN_FILE=$STATE/desktop.token
exec "$SHARE/venv/bin/python" -m aiws.cli "\$@"
EOF
cat > "$BIN/aiws-orb" <<EOF
#!/bin/sh
# Marina, the sphere. \`aiws-orb --toggle\` opens or closes her chat.
export AIWS_TOKEN_FILE=$STATE/desktop.token AIWS_PYTHON=$SHARE/venv/bin/python PYTHONPATH=$SHARE/src
exec "$SHARE/electron/electron" --ozone-platform-hint=auto "$SHARE/orb" "\$@"
EOF
cat > "$BIN/aiws-control" <<EOF
#!/bin/sh
# The Control Centre, in the browser (no WebKitGTK needed).
exec xdg-open "http://127.0.0.1:7300/ui/#token=\$(cat $STATE/desktop.token)"
EOF
cat > "$BIN/aiws-agent-stop" <<EOF
#!/bin/sh
# Stop the assistant now: tell the gateway, then kill it outright.
"$BIN/ai" agent stop >/dev/null 2>&1
systemctl --user kill -s KILL aiws-agent.service; systemctl --user restart aiws-agent.service
EOF
chmod 755 "$BIN/ai" "$BIN/aiws-orb" "$BIN/aiws-control" "$BIN/aiws-agent-stop"

systemctl --user daemon-reload
systemctl --user enable --now aiwsd.service aiws-agent.service

say "done"
missing=""
for t in tmux wtype ydotool tailscale; do command -v $t >/dev/null || missing="$missing $t"; done
python3 -c "import pyatspi" 2>/dev/null || missing="$missing python-atspi"
[ -z "$missing" ] || echo "Needs sudo to install:$missing  (sudo pacman -S --needed$missing)"
