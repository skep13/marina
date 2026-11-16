# The laptop: CachyOS + Hyprland/Caelestia (Linux only)

Decision (2026-10-27): lab3 stays on Proxmox as the AI server (Marina,
Songbird, llama-swap in ct110). The AI workstation layer goes on the new
laptop and uses lab3's models over Tailscale. Linux only (decided
2026-10-28): no Windows. Games on Linux: Minecraft native; Roblox via Sober
(unofficial); Zenless Zone Zero only via unofficial launchers (ban risk);
Roblox Studio not available.

## Hardware

MSI Cyborg 15 B2RWEKG-021UK: Intel Core 7 240H (10 cores), NVIDIA RTX
5050 8 GB GDDR7, 16 GB DDR5-5600, 512 GB NVMe, 15.6" 1080p, Windows 11
Home. Check the actual sticker; listings for this base model vary.

## Before installing

1. Update the MSI BIOS if an update is offered (from the MSI support page).
2. Secure Boot off for the install (CachyOS default).
3. Put the CachyOS ISO (or the custom AIWS ISO) on the Ventoy stick.

## Install

* CachyOS installer → **Erase disk** → filesystem **btrfs** (snapshots before
  every update, bootable from the menu) → bootloader **Limine** → tick
  **encrypt** (it's a laptop that travels) → desktop **Hyprland**.
* At the login screen choose **Hyprland (uwsm-managed)**.
* Let `chwd` install the NVIDIA open driver.
* `setup.sh` then installs the Caelestia shell (`caelestia-cli` from the
  AUR, then `caelestia install`, which asks first because it replaces
  `~/.config/hypr`). Caelestia updates with `caelestia update`; that is a
  full system update too.

### Two GPUs (Intel iGPU + RTX 5050)

Run the desktop on the Intel iGPU and keep the RTX 5050 for games, Blender
and the local model: better battery and fewer NVIDIA/Wayland quirks.
Hyprland picks its GPU at startup, before it reads any config, so this
goes in uwsm's environment file `~/.config/uwsm/env-hyprland` (Caelestia
starts Hyprland through uwsm). Check which card is which first with
`ls -l /dev/dri/by-path` (the Intel iGPU is usually PCI 00:02.0):

```bash
export AQ_DRM_DEVICES=/dev/dri/card1:/dev/dri/card0   # Intel first, NVIDIA second
```

Apps that should use the NVIDIA card: `prime-run <app>`. llama-server
finds the RTX 5050 through CUDA either way.

## After install: one command

```bash
git clone <this repo> && cd marina/aiws/laptop && ./setup.sh
```

`setup.sh` is idempotent (safe to re-run) and does:

| area | what |
|---|---|
| AI layer | `aiws-core` package: aiwsd gateway, assistant, `ai` CLI, Ask popup, Control Centre |
| models | lab3's model (`lab3-marina`) over Tailscale as the default for chat/code/vision; a small local model on the RTX 5050 (llama.cpp CUDA) for offline and fast completions |
| network | Tailscale with `--accept-routes`, so 192.168.1.0/24 (lab3) is reachable from anywhere |
| desktop | Caelestia on Hyprland; one `dofile` line in `~/.config/caelestia/hypr-user.lua` adds Super+Space (ask), Super+Escape (stop), Super+A (Control Centre) and window rules. Caelestia's own files aren't edited, so its updates keep working |
| assistant on Wayland | screenshots `grim`, window info `hyprctl`, typing `wtype`, clicks `ydotool` (your user joins group `input` for `/dev/uinput`), selection `wl-paste` |
| college/dev/hardware | LibreOffice, VSCodium, git, Python, PlatformIO/esptool, KiCad, Arduino serial access, OrcaSlicer, Blender, Prism Launcher |

## The look: the Mac's Miku setup, on Linux

Everything matches the Mac (`desktop/rice/`), installed by `setup.sh`:

| Mac | Laptop |
|---|---|
| kitty, Miku palette, Menlo 13 | same kitty.conf; DejaVu Sans Mono (Menlo's source font); zsh inside kitty |
| oh-my-zsh `miku` prompt, `mem` | same prompt; `mem` reads /proc instead of macOS tools |
| fastfetch Miku logo | same config and logo |
| Übersicht Mond clock | Quickshell desktop widget (`qs -c mond`), same layout, fonts and bars |
| Rectangle (Ctrl+Option) | `snap-window` on Ctrl+Alt: arrows = halves, U/I/J/K = quarters, D/F/G = thirds, E/T = two-thirds, Return = maximise, C = centre, Backspace = back to tiling |
| cava gradient | same three colours |
| wallpaper | set in Caelestia, which derives the shell's colours from it |

The wallpapers, Anurati + Inter fonts and the fastfetch logo aren't in the
repo (third-party art, font licence). They're in
`desktop/rice/miku-assets.tar.gz` on the Mac (git-ignored). Send it with
`tailscale file cp miku-assets.tar.gz <laptop>:` and on the laptop
`tailscale file get ~/Downloads`, or copy it over USB, before `setup.sh`.

Not carried over: drag-a-window-to-the-edge snapping (Hyprland has no
equivalent; tiling places windows for you), and the macOS Dock/accent tweaks.

## Using lab3 from the laptop

The Tailscale node `homelab` (lab1 ct102) already advertises
192.168.1.0/24. With routes accepted, the laptop reaches llama-swap on
ct110 (192.168.1.15:8080) wherever it is. The key lives only in
`/etc/aiws/secrets.env` on the laptop.

Note: `homelab` also has Tailscale Funnel on for tcp 10000, which is
public. Check that's intended.

## Superseded

`build/` (Debian live-build ISO for lab3) is kept for reference but is
no longer the target.
