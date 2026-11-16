#!/bin/bash
# Runs once, at the first Hyprland login (rice.lua starts it): the bits of
# setup that need a live session. Leaves a marker so it never runs again.
marker="${XDG_STATE_HOME:-$HOME/.local/state}/aiws/firstlogin.done"
[ -f "$marker" ] && exit 0
mkdir -p "$(dirname "$marker")"
sleep 3                                   # let the shell come up

# Caelestia's colour scheme from the Miku wallpaper
wall="$HOME/Pictures/Wallpapers/miku-3840x2160.png"
if command -v caelestia >/dev/null; then
  [ -f "${XDG_STATE_HOME:-$HOME/.local/state}/caelestia/scheme.json" ] || caelestia scheme set -n caelestia
  [ -f "$wall" ] && caelestia wallpaper -f "$wall"
fi
# zsh for new terminals (kitty already runs zsh; this covers the rest).
# Needs your password once; skipped quietly if cancelled.
[ "${SHELL##*/}" = zsh ] || pkexec chsh -s /usr/bin/zsh "$USER" 2>/dev/null

touch "$marker"
