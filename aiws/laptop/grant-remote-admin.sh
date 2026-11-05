#!/usr/bin/env bash
# Run ONCE on the laptop, yourself:  sudo bash grant-remote-admin.sh [user]
#
# Gives the user passwordless sudo so the Mac (via `laptop root ...`) can do
# system-level setup without a password prompt. Anyone who gets that user's
# SSH key gets root, so keep the Mac's key safe. To undo:
#   sudo rm /etc/sudoers.d/90-aiws-remote
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run with sudo"; exit 1; }
U="${1:-${SUDO_USER:-friereon}}"
F=/etc/sudoers.d/90-aiws-remote
tmp=$(mktemp)
printf '# aiws: remote admin from the Mac (laptop root ...)\n%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "$U" > "$tmp"
visudo -cf "$tmp" >/dev/null
install -m 440 -o root -g root "$tmp" "$F"; rm -f "$tmp"
# Let the user change Tailscale settings without sudo as well.
command -v tailscale >/dev/null && tailscale set --operator="$U" --accept-routes || true
echo "done: $U has passwordless sudo ($F); tailscale accepts subnet routes"
