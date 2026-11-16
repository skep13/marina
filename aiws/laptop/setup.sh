#!/usr/bin/env bash
# Set up the AI workstation layer on CachyOS / Arch with Hyprland + Caelestia.
# Run as your normal user (it uses sudo where needed). Safe to re-run.
#
#   ./setup.sh                 everything
#   ./setup.sh --no-apps       skip the college/dev/hardware apps
#   ./setup.sh --no-local-ai   skip llama.cpp CUDA + the local model
#   ./setup.sh --no-tailscale  leave Tailscale alone (already set up, or testing)
#   ./setup.sh --no-caelestia  don't install Caelestia (already have it, or testing)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
APPS=1 LOCAL_AI=1 TAILSCALE=1 CAELESTIA=1
for a in "$@"; do
  case $a in
    --no-apps) APPS=0 ;;
    --no-local-ai) LOCAL_AI=0 ;;
    --no-tailscale) TAILSCALE=0 ;;
    --no-caelestia) CAELESTIA=0 ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done

say() { printf '\n\033[1;33m== %s\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

. /etc/os-release
case "${ID:-} ${ID_LIKE:-}" in
  *arch*|*cachyos*) ;;
  *) echo "This is for CachyOS / Arch (found ${PRETTY_NAME:-unknown})." >&2; exit 1 ;;
esac
[ "$(id -u)" -ne 0 ] || { echo "Run as your normal user, not root." >&2; exit 1; }

# AUR helper: CachyOS ships paru.
aur() {
  if have paru; then paru -S --needed --noconfirm "$@"
  elif have yay; then yay -S --needed --noconfirm "$@"
  else echo "   (no AUR helper; skipped: $*)"; return 0; fi
}

say "Base packages"
sudo pacman -S --needed --noconfirm \
  base-devel git python python-fastapi uvicorn python-httpx python-yaml \
  python-gobject gtk3 webkit2gtk-4.1 python-atspi at-spi2-core grim wtype wl-clipboard \
  ydotool tmux openssh sqlite podman distrobox tailscale

say "Packages: llama-swap and aiws-core"
for p in llama-swap aiws-core; do
  (cd "$here/$p" && makepkg -sif --noconfirm --needed)
done
sudo systemd-sysusers
sudo systemd-tmpfiles --create /usr/lib/tmpfiles.d/aiws.conf
sudo gpasswd -a "$USER" aiws >/dev/null
sudo gpasswd -a "$USER" uucp >/dev/null   # serial ports: ESP32, Arduino
# /dev/uinput for ydotool (the assistant's clicks on Wayland). Any program
# running as you can then inject input; the assistant already can.
sudo gpasswd -a "$USER" input >/dev/null
sudo udevadm control --reload && sudo udevadm trigger --name-match=uinput || true

if [ "$LOCAL_AI" = 1 ]; then
  say "Local AI on the GPU"
  if have nvidia-smi && nvidia-smi -L >/dev/null 2>&1; then
    nvidia-smi -L
    have llama-server || sudo pacman -S --needed --noconfirm llama.cpp-cuda 2>/dev/null \
      || aur llama.cpp-cuda
  else
    echo "   No NVIDIA driver answering. On CachyOS run: sudo chwd -a, reboot, re-run this."
    echo "   Skipping the local model; lab3 still works."
  fi
fi

if [ "$TAILSCALE" = 1 ]; then
  say "Tailscale (reaches lab3 from anywhere)"
  sudo systemctl enable --now tailscaled
  if ! tailscale status >/dev/null 2>&1; then
    echo "   Log in when the link appears:"
    sudo tailscale up --accept-routes
  else
    sudo tailscale set --accept-routes
  fi
fi

say "lab3 key"
if ! sudo grep -q '^AIWS_KEY_LAB3=.' /etc/aiws/secrets.env; then
  read -rsp "   llama-swap API key for lab3 (input hidden, Enter to skip): " key || key=; echo
  if [ -n "$key" ]; then
    printf 'AIWS_KEY_LAB3=%s\n' "$key" | sudo tee -a /etc/aiws/secrets.env >/dev/null
  fi
  unset key
else
  echo "   already set"
fi

say "Services"
sudo systemctl enable --now llama-swap.service aiwsd.service
systemctl --user daemon-reload
systemctl --user enable ydotool.service 2>/dev/null || true

if [ "$CAELESTIA" = 1 ]; then
  say "Caelestia shell"
  have caelestia || aur caelestia-cli
  if [ ! -f "$HOME/.config/hypr/hyprland.lua" ] && have caelestia; then
    echo "   Caelestia's installer sets up Hyprland, the shell and its app configs"
    echo "   (it replaces ~/.config/hypr and some others)."
    read -rp "   Run 'caelestia install' now? [y/N] " yn || yn=
    [ "${yn,,}" = y ] && caelestia install
  else
    echo "   already installed"
  fi
fi

say "Hyprland keys (Super+Space Marina, Super+Escape stop, Super+A control centre)"
user_lua="$HOME/.config/caelestia/hypr-user.lua"
line='dofile("/usr/share/aiws/hypr/aiws.lua")'
mkdir -p "$(dirname "$user_lua")"
touch "$user_lua"
if ! grep -qF "$line" "$user_lua"; then
  printf '\n-- AI workstation keys and window rules\n%s\n' "$line" >> "$user_lua"
  echo "   added to $user_lua"
  have hyprctl && hyprctl reload >/dev/null 2>&1 || true
else
  echo "   already there"
fi

say "Miku rice (kitty, zsh prompt, fastfetch, cava, Mond clock, window snapping)"
rice="$here/../desktop/rice"
# pipewire-jack first, or cava pulls in jack2, which fights PipeWire.
sudo pacman -S --needed --noconfirm pipewire-jack kitty zsh fastfetch cava ttf-dejavu python
have qs || aur quickshell-git
[ -d "$HOME/.oh-my-zsh" ] || git clone -q --depth 1 https://github.com/ohmyzsh/ohmyzsh "$HOME/.oh-my-zsh"

# Wallpapers, Anurati + Inter fonts and the fastfetch logo come from the Mac as
# miku-assets.tar.gz (Taildrop or USB), never from the public repo.
assets=""
for f in "$HOME/Downloads/miku-assets.tar.gz" "$HOME/miku-assets.tar.gz" "$rice/miku-assets.tar.gz"; do
  [ -f "$f" ] && { assets="$f"; break; }
done
if [ -n "$assets" ]; then
  tmp=$(mktemp -d); tar -xzf "$assets" -C "$tmp"
  mkdir -p "$HOME/.local/share/fonts" "$HOME/Pictures/Wallpapers" "$HOME/.config/fastfetch"
  cp "$tmp"/miku-assets/fonts/* "$HOME/.local/share/fonts/"
  cp "$tmp"/miku-assets/wallpapers/* "$HOME/Pictures/Wallpapers/"
  cp "$tmp"/miku-assets/fastfetch/miku-ascii.ansi "$HOME/.config/fastfetch/"
  rm -rf "$tmp"; fc-cache -f >/dev/null
  echo "   assets from $assets"
else
  echo "   miku-assets.tar.gz not found in ~/Downloads: send it from the Mac with"
  echo "   'tailscale file cp miku-assets.tar.gz <laptop>:' then 'tailscale file get ~/Downloads', and re-run."
fi

# Put a config in place; keep whatever was there as <file>.before-miku.
put() {
  mkdir -p "$(dirname "$2")"
  if [ -f "$2" ] && ! cmp -s "$1" "$2"; then
    [ -f "$2.before-miku" ] || cp "$2" "$2.before-miku"
  fi
  install -m "${3:-644}" "$1" "$2"
}
put "$rice/kitty/kitty.conf"        "$HOME/.config/kitty/kitty.conf"
put "$rice/zsh/zshrc"               "$HOME/.zshrc"
put "$rice/zsh/miku.zsh"            "$HOME/.config/miku-theme/miku.zsh"
put "$rice/zsh/miku.zsh-theme"      "$HOME/.oh-my-zsh/custom/themes/miku.zsh-theme"
put "$rice/fastfetch/config.jsonc"  "$HOME/.config/fastfetch/config.jsonc"
put "$rice/cava/config"             "$HOME/.config/cava/config"
put "$rice/mond/shell.qml"          "$HOME/.config/quickshell/mond/shell.qml"
put "$rice/mond/stats.sh"           "$HOME/.config/quickshell/mond/stats.sh" 755
put "$rice/hypr/snap-window"        "$HOME/.local/bin/snap-window" 755
put "$rice/hypr/rice.lua"           "$HOME/.config/miku-theme/rice.lua"

rline='dofile(os.getenv("HOME") .. "/.config/miku-theme/rice.lua")'
if ! grep -qF "$rline" "$user_lua"; then
  printf '\n-- Miku rice: Rectangle-style snapping (Ctrl+Alt), Mond clock\n%s\n' "$rline" >> "$user_lua"
fi

# kitty as Caelestia's terminal (Super+T), if hypr-vars.lua is still empty.
vars="$HOME/.config/caelestia/hypr-vars.lua"
if [ ! -s "$vars" ] || grep -qx 'return {}' "$vars"; then
  printf 'return {\n    terminal = "kitty",\n}\n' > "$vars"
elif ! grep -q 'terminal' "$vars"; then
  echo "   add  terminal = \"kitty\"  to $vars yourself (it has your own settings)"
fi

# Wallpaper: Caelestia builds its colour scheme from it, so the shell goes periwinkle too.
wall="$HOME/Pictures/Wallpapers/miku-3840x2160.png"
if [ -f "$wall" ] && have caelestia; then
  caelestia wallpaper -f "$wall" >/dev/null 2>&1 || echo "   set the wallpaper from Caelestia's launcher: $wall"
fi
have hyprctl && hyprctl reload >/dev/null 2>&1 || true

if [ "$APPS" = 1 ]; then
  say "College, dev and hardware apps"
  sudo pacman -S --needed --noconfirm \
    libreoffice-fresh firefox thunderbird \
    python-pip python-virtualenv nodejs npm \
    esptool arduino-cli kicad blender prismlauncher \
    || echo "   some repo packages failed; carry on"
  aur vscodium-bin orca-slicer-bin platformio-core || true
fi

say "Done"
cat <<EOF
Log out and back in (for the aiws and input groups), then:
  ai status            gateway, models, memory
  ai models            lab3-marina should be ready (○)
  Super+Space          open Marina (the sphere, bottom-right)
Local model (optional, ~4.7 GB):
  sudo -u aiws curl -L -o /var/lib/aiws/models/qwen2.5-coder-7b-instruct-q4_k_m.gguf \\
    https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf
  ai models apply
EOF
