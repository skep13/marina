# Laptop handoff: finish the AI workstation on this machine

You're on my new laptop. Most of the software was built and tested on my Mac
and on Arch containers; your job is to install it here, port the parts that
assumed Hyprland to **MangoWM**, and add the MSI controls. Test everything on
this real machine and tell me plainly what works and what doesn't.

## This machine
- MSI Cyborg 15 B2RWEKG-021UK: Intel Core 7 240H (10 cores), NVIDIA RTX 5050
  8 GB + Intel iGPU, 16 GB DDR5, 512 GB NVMe, 15.6" 1080p 144 Hz, 4-zone RGB keyboard.
- **CachyOS only** (no Windows). btrfs + Limine (bootable snapshots), disk
  encryption. Hostname `marina`, user `j`.
- Desktop: **MangoWM** (Wayland compositor based on dwl). Not Hyprland, not Caelestia.

## My homelab (the big model runs there)
- Proxmox: lab1 192.168.1.10, lab2 192.168.1.11, lab3 192.168.1.13.
- **lab3 ct110** runs **llama-swap on 192.168.1.15:8080** with Marina's model
  (Qwen3.6-35B-A3B). It needs an API key: **ask me for it; never write it into
  a file that gets committed.** It goes in `/etc/aiws/secrets.env` as
  `AIWS_KEY_LAB3=...` (root:aiws 0640), or through Marina's first-boot card.
- **Tailscale**: node `homelab` advertises 192.168.1.0/24. On this laptop:
  `sudo tailscale up --accept-routes`, then 192.168.1.15 works from anywhere.
- Don't change lab3/ct110 or other homelab services unless I ask.

## What's in this bundle
- `aiws/`: the project (from my `marina` repo, not yet committed there).
  - `src/aiws/`: aiwsd gateway (OpenAI-compatible API, model roles
    `ai:chat`/`ai:code`/`ai:vision`, projects, jobs, Control Centre UI), the
    assistant (`agent/`), `screen.py` (screen/pointer/keyboard per platform), CLI `ai`.
  - `orb/`: **Marina**, an Electron app: an animated sphere bottom-right that
    pulses when speaking/typing, colour picker for every part and state, chat
    that sees what I'm doing (focus log, selection, screenshot on demand,
    watch mode), "do it" hands tasks to the assistant, first-boot card for the
    lab3 key and Tailscale. Tested end to end on the Mac against lab3.
  - `laptop/`: `setup.sh` (installs everything), `aiws-user-setup` (per-user,
    no prompts), PKGBUILDs for `aiws-core` and `llama-swap`.
  - `desktop/rice/`: my Mac look ported: kitty, zsh + oh-my-zsh `miku`
    prompt, fastfetch logo config, cava, the **Mond clock** (Quickshell
    layer widget), `snap-window` (Rectangle-style snapping), `rice.lua` (Hyprland).
  - `desktop/hypr/aiws.lua`: Hyprland keys and rules (**needs a Mango version**).
  - `iso/`: a custom CachyOS ISO build (not needed now; reference only).
  - `docs/`: ARCHITECTURE.md, PLAN.md, LAPTOP.md.
  - `tests/`: `python -m unittest discover -s aiws/tests` (22 tests).
- `assets/miku-assets.tar.gz`: my wallpapers, Anurati + Inter fonts,
  fastfetch logo. **Private: never commit or publish.**
- `reference/mango/`: Mango's own docs and sample config, copied from its repo.

## Decisions already made (don't reopen)
- The assistant acts **without approval prompts**; I stop it with ■ stop in
  Marina or the stop key.
- Marina is a **sphere**, not a character.
- Don't apply the Miku palette to *new* designs; it's only my ported setup.
- I want the desktop to look **unique**, not like a stock rice.
- Git: commit as me (`skep13`). **No AI/Claude attribution** in commits, PRs,
  code or docs.

## Tasks, in order

### 1. Install the base (adapt `laptop/setup.sh` for Mango)
`setup.sh` assumes Hyprland + Caelestia. Run its parts that don't, or add a
`--mango` path: base packages, build/install `llama-swap` and `aiws-core`
with makepkg, groups (`aiws`, `input` for ydotool, `uucp` for serial),
services (`aiwsd`, `llama-swap`, `tailscaled`, user `ydotool`), Tailscale, the
lab3 key, apps. Skip the Caelestia section.

### 2. Port the screen tools to Mango (`src/aiws/screen.py`)
Add a `mango` backend (when `MANGO_INSTANCE_SIGNATURE` is set). Mango's IPC
CLI is `mmsg` (see `reference/mango/ipc.md`):
- focused window: `mmsg get focusing-client` (JSON; fields include id,
  appid, title, x, y, width, height, monitor, tags; check the real output)
- monitors: `mmsg get all-monitors`; clients: `mmsg get all-clients`
- actions: `mmsg dispatch <func>,[args] [client,<id>]`
- events: `mmsg watch focusing-client` (good for the activity log instead of polling)
Screenshots (`grim`), typing (`wtype`), clicks (`ydotool`) and selection
(`wl-paste`) already work on any wlroots compositor; pointer moves need a
Mango way (check `reference/mango` for a cursor/warp dispatch, else
`ydotool mousemove --absolute`). Add unit tests like `tests/test_screen.py`.

### 3. Mango config (`~/.config/mango/config.conf`)
Syntax: `bind=MODS,key,func,args`, e.g. `bind=SUPER,space,spawn,aiws-orb --toggle`.
Window rules: see `reference/mango/rules.md`. Wanted:
- `SUPER+space` → `aiws-orb --toggle` (Marina); `SUPER+Escape` → `ai agent stop`;
  a key for `aiws-control`.
- Marina's window (title `Marina`): floating, on all tags (global/overlay),
  no border/shadow/blur, opaque, bottom-right. Then update `orb/main.js`
  `hyprAnchor()` with a Mango version (or a window rule that pins it bottom-right).
- Autostart: `/usr/lib/aiws/session-setup`, `aiws-orb`, `qs -c mond -d`.
- **Rectangle-style snapping on Ctrl+Alt** (my Mac muscle memory): arrows =
  halves, U/I/J/K = quarters, D/F/G = thirds, E/T = two-thirds, Return =
  maximise, C = centre, Backspace = back to tiling. Port
  `desktop/rice/hypr/snap-window` from hyprctl to mmsg (or Mango's own
  dispatches for floating geometry).

### 4. The rice (from `desktop/rice/`, assets from `assets/miku-assets.tar.gz`)
kitty.conf, `~/.zshrc` + oh-my-zsh + `miku` theme + `miku.zsh`, fastfetch
config + logo, cava config, fonts into `~/.local/share/fonts`, wallpaper
`miku-3840x2160.png` (Mango has no wallpaper itself: use swaybg or similar),
Mond clock in `~/.config/quickshell/mond/`. Back up anything you replace as
`<file>.before-miku`.

### 5. A shell for Mango (bar, launcher, notifications)
No Caelestia here. Build my own Quickshell shell, Mango-aware via `mmsg watch
all-tags` / `focusing-client`, so it looks unique. Start small (bar with tags,
clock, network, battery, volume, tray, Marina's status) and **show me the design
before building big pieces**. Notifications: a Quickshell notification server
or mako for now. Launcher: fuzzel or rofi-wayland for now.

### 6. MSI controls (replacing MSI Center)
Check the hardware before installing anything:
- **Performance profiles:** `power-profiles-daemon` (`powerprofilesctl`)
  works on any laptop; expose it in the bar/Control Centre.
- **Fans, Cooler Boost, battery charge limit, MSI performance modes:**
  **MControlCenter** (AUR) on the **msi-ec** driver, only if this laptop's EC
  firmware is supported. Check `sudo dmidecode -s bios-version`,
  `cat /sys/class/dmi/id/product_name`, and msi-ec's supported list / issues
  for "Cyborg 15 B2R". If unsupported, say so; don't force EC writes.
- **Keyboard RGB (4-zone):** find the controller first (`lsusb`, look for
  MSI 1462 or SteelSeries 1038 HID devices; `ls /sys/class/leds`). Candidates:
  **LightShow** (github.com/nixfred/lightshow, MSI Mystic Light keyboards; a
  Cyborg 15 MS-1606 is reported) or **OpenRGB**. I want an easy way to change
  colours, ideally a GUI or a bar/Control Centre picker like Marina's colour pickers.
- GPU: run the desktop on the Intel iGPU, NVIDIA for games/Blender/local model.

### 7. Local model
`llama.cpp-cuda` (AUR) + a ~7B coder model on the RTX 5050 (see
`laptop/etc/aiws/models.d/qwen2.5-coder-7b.yaml`), set as `ai:fast`.

### 8. Apps
College: libreoffice-fresh, firefox, thunderbird. Dev: vscodium, git,
python-pip, python-virtualenv, nodejs, npm, podman, distrobox. Hardware/3D:
esptool, arduino-cli, platformio-core, kicad, blender, orca-slicer (AUR).
Games: steam, prismlauncher; Roblox via Sober (unofficial). Zenless Zone
Zero only via unofficial launchers (ban risk); Roblox Studio isn't available on Linux.

## How to work
- Verify on this machine before saying something works; list what's untested.
- Never put secrets in tracked files.
- Commit to the `marina` repo (branch `aiws-laptop`) when I say so; keep
  `assets/`, `miku-assets.tar.gz` and `companion/frames/` out of git.
