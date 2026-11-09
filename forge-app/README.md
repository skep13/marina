# Forge.app

A native macOS window for **Forge**, the coding-only agent: DeepSeek Harness on
this Mac driving the KAT-Coder-V2.5-Dev model that llama-swap serves on lab3
(model id `forge`).

The app (Rust, `tao` + `wry` WebKit window):

- checks that lab3 (`192.168.1.15:8080`) answers over the ethernet cable;
- starts `dsh --profile web` from `~/.forge` (Node 24, telemetry off) on a free
  port, in your home folder, and opens its tokenised URL in the window;
- stops the server when you quit (⌘Q or close the window). A small `sh`
  supervisor also stops it within ~2 s if the app is force-quit or crashes.

Menus: **View → Reload** (⌘R), **View → Open in Browser** (⇧⌘O), and a
standard Edit menu, so copy and paste work. Server output goes to
`~/.forge/app.log`.

## Install

```bash
./macos/install.sh             # build, create ~/Applications/Forge.app, pin to Dock
./macos/install.sh --build     # force a rebuild first
./macos/install.sh --no-dock   # don't touch the Dock
./macos/install.sh --uninstall # remove the app and its Dock tile (~/.forge is kept)
```

The first launch asks for **Local Network** access; click Allow, or Forge
can't reach lab3. If you miss the prompt, turn Forge on in System Settings →
Privacy & Security → Local Network.

Needs the Forge setup in `~/.forge` (`app/` with `@deepseek-ai/dsh`, `home/`
config, `lab3.key`) and `brew install node@24`.
