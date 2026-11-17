#!/usr/bin/env bash
# Put the newest signed Browser agent on the CachyOS laptop: copies the .xpi to
# ~/Downloads and the lab3 key to ~/.config/lab3/browser.key (mode 600), then
# opens the .xpi in the laptop's Firefox if a desktop session is running.
#
#   firefox/install-laptop.sh [user@host]      default marina@192.168.1.78
set -euo pipefail
HOST="${1:-marina@192.168.1.78}"
HERE="$(cd "$(dirname "$0")" && pwd)"
XPI="$(ls -t "$HERE"/dist/browser-agent-*-signed.xpi 2>/dev/null | head -1)"
KEY="$HOME/.config/lab3/browser.key"

[ -n "$XPI" ] || { echo "No signed .xpi in $HERE/dist; run python3 firefox/sign.py first." >&2; exit 1; }
[ -f "$KEY" ] || { echo "No $KEY on this Mac." >&2; exit 1; }

echo "→ $HOST: $(basename "$XPI")"
scp -q "$XPI" "$HOST:Downloads/"
ssh "$HOST" 'mkdir -p ~/.config/lab3 && umask 077 && cat > ~/.config/lab3/browser.key' < "$KEY"

# Hand the .xpi to the running Firefox (it shows the Add prompt there).
ssh "$HOST" "f=~/Downloads/$(basename "$XPI");
  pid=\$(pgrep -u \$USER -x firefox | head -1 || true)
  if [ -n \"\$pid\" ]; then
    export \$(tr '\\0' '\\n' < /proc/\$pid/environ | grep -E '^(DISPLAY|WAYLAND_DISPLAY|XDG_RUNTIME_DIR|DBUS_SESSION_BUS_ADDRESS)=' | xargs)
    nohup firefox \"\$f\" >/dev/null 2>&1 &
    echo 'Opened in Firefox: click Add on the laptop.'
  else
    echo \"Firefox isn't running; open \$f in it, or drag it onto a window.\"
  fi"
echo "Key is in ~/.config/lab3/browser.key on the laptop: paste it into cfg once."
