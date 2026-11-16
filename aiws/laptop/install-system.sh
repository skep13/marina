#!/bin/bash
# The system-level half of the laptop setup: everything that needs sudo.
# Run once, as your normal user; it asks for your password once.
#   bash install-system.sh
set -euo pipefail
[ "$(id -u)" -ne 0 ] || { echo "Run as your normal user (it uses sudo itself)." >&2; exit 1; }
sudo -n true 2>/dev/null || sudo -v   # no prompt when passwordless sudo is set up

echo "== assistant tools: terminal, typing, clicking, accessibility"
sudo pacman -S --needed --noconfirm tmux wtype ydotool python-atspi

echo "== Tailscale (reach lab3 from anywhere)"
sudo pacman -S --needed --noconfirm tailscale
sudo systemctl enable --now tailscaled

echo "== apps"
sudo pacman -S --needed --noconfirm \
  vscodium libreoffice-fresh thunderbird \
  python-pip nodejs npm podman distrobox \
  esptool arduino-cli platformio-core kicad blender prismlauncher \
  cava \
  steam || echo "   (some apps failed; the rest are in)"

echo "== permissions: clicks on Wayland (/dev/uinput) and serial ports (ESP32/Arduino)"
echo 'KERNEL=="uinput", GROUP="input", MODE="0660", OPTIONS+="static_node=uinput"' \
  | sudo tee /etc/udev/rules.d/60-aiws-uinput.rules >/dev/null
sudo udevadm control --reload && sudo udevadm trigger --name-match=uinput || true
sudo usermod -aG input,uucp "$USER"
systemctl --user enable --now ydotool.service 2>/dev/null || true

echo "== Tailscale login (opens a link; skip with Ctrl+C if you'd rather do it later)"
[ -t 0 ] && sudo tailscale up --accept-routes || echo "   run: sudo tailscale up --accept-routes"

echo
echo "Done. Log out and back in once, so the input/uucp groups apply."
