# modelctl

A fast, keyboard-driven TUI for managing the LLM models that
[llama-swap](https://github.com/mostlygeek/llama-swap) serves to the homelab
(lab3, AMD Radeon 780M, llama.cpp/Vulkan). One GPU, models swapped one at a
time — `modelctl` lets you see what's loaded, swap it, edit llama-swap's config
safely, and pull new GGUFs from Hugging Face straight onto lab3.

```
┌ modelctl ─ [Models] Config Download   http://192.168.1.15:8080 ┐
│ models served by llama-swap                                    │
│   MODEL      STATE        CTX   CAPS          TTL              │
│ ▶ marina     ○ unloaded   64K   vision tools  resident         │
│   songbird   ● loaded     32K   tools         1200s            │
└────────────────────────────────────────────────────────────────┘
 ↑/↓ select • l load/swap • u unload all • r refresh • 2 config • 3 download • q quit
```

## What it does

1. **Switch the active model.** Lists everything llama-swap serves
   (`GET /v1/models`), shows which is loaded (`/running`), and swaps on a
   keystroke. Loading is done by proxying the model's `/upstream/<model>/health`
   — llama-swap brings the upstream llama-server up without generating any
   tokens. Unload (free the GPU) via `POST /unload`, behind a confirm.
2. **Edit model config.** Views llama-swap's `config.yaml` from lab3 and opens
   it in `$EDITOR`. On save it **backs up** (timestamped `.bak`), **validates**
   with `llama-swap -validate` (a bad config is rejected and never written), then
   **atomically** renames it into place. llama-swap runs with `-watch-config`, so
   the rename alone triggers a reload.
3. **Download models.** Pulls a GGUF from Hugging Face by repo id + filename
   **onto lab3** (driven over SSH — never through this machine), with a live
   progress bar + transfer rate. Downloads are resumable (`curl -C -`) and land
   in lab3's models dir atomically (`<file>.part` → `<file>`).

## Configuration

The llama-swap API key is **never hardcoded**. It is read, in order, from:

1. `--api-key` / `$MODELCTL_API_KEY`
2. `$MARINA_LAB3_KEY`
3. the key file `~/.marina/agent-keys.env` (line `MARINA_LAB3_KEY=...`)

Defaults match the current lab3 deployment and can be overridden by flag or env:

| setting      | flag             | env                    | default                          |
|--------------|------------------|------------------------|----------------------------------|
| host         | `--host`         | `MODELCTL_HOST`        | `192.168.1.15`                   |
| port         | `--port`         | `MODELCTL_PORT`        | `8080`                           |
| ssh target   | `--ssh`          | `MODELCTL_SSH`         | `root@<host>`                    |
| models dir   | `--models-dir`   | `MODELCTL_MODELS_DIR`  | `/models`                        |
| config path  | `--config-path`  | `MODELCTL_CONFIG_PATH` | `/opt/llama-swap/config.yaml`    |
| binary path  |                  | `MODELCTL_BINARY`      | `/opt/llama-swap/llama-swap`     |

SSH must be key-based and non-interactive (the app uses `BatchMode=yes`).

## Usage

```bash
cargo build --release
./target/release/modelctl            # launch the TUI

# non-interactive helpers (handy for scripts):
modelctl --list                      # print the model table and exit
modelctl --load marina               # swap to a model and exit
```

### macOS: install as a Dock app

`macos/install.sh` builds the binary, installs it to `~/.local/bin/modelctl`,
wraps it in `~/Applications/modelctl.app` (which opens the TUI in Terminal),
generates an icon, and adds it to the Dock. It's idempotent — re-run it after a
rebuild to refresh the installed copy.

```bash
./macos/install.sh            # build (if needed), install, add to Dock
./macos/install.sh --no-dock  # install without touching the Dock
./macos/install.sh --build    # force a fresh release build first
./macos/install.sh --uninstall
```

The icon step needs `python3` + Pillow and `iconutil` (both ship with a typical
macOS + Xcode CLT setup); without them the app falls back to the generic icon.

### Keys

- **Models:** `↑/↓` select · `l`/Enter load-swap · `u` unload all · `r` refresh · `2` config · `3` download · `q` quit
- **Config:** `↑/↓`/PgUp/PgDn scroll · `e` edit in `$EDITOR` · `r` reload · `1` models · `3` download · `q` quit
- **Download:** `Tab`/`↑↓` move between fields · type repo id / filename / revision · `Enter` start · `Esc` back · `Ctrl+C` quit

## Notes

- Loading a large MoE can take a while to map into GTT; the status line shows
  the swap in progress and `/running` state (`loading` → `ready`).
- The download screen refuses to clobber a file that already exists in the
  models dir — remove it on lab3 first to re-pull.
- Requires: a Rust toolchain to build; `ssh`, and on lab3 `curl` + the
  `llama-swap` binary.
