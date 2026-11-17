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

**YubiKey lock.** Forge opens only after you plug in your YubiKey and tap it.
The key signs a fresh random challenge with its SSH key (`~/.ssh/id_ed25519_sk`)
and the app checks the signature against the public key pinned in
`~/.forge/yubikey_allowed_signers` (written by `install.sh`). Unplugging the
key while Forge is open stops the harness and shows a locked screen; plug it
back in and press **Unlock**. Needs Homebrew OpenSSH (`brew install openssh`).
The `forge` command-line launcher is not gated.

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

## Look

The theme is the `dsh-forge-theme` plugin in this folder: an ember-on-charcoal
palette, the FORGE wordmark, drifting sparks, and plain time-of-day greetings
on the start screen. `~/.forge/home/profiles/web/package.json` links it in, so
an edit shows up after ⌘R in Forge. Edit `client.template.js` or `build.py`,
then regenerate the bundle (`lib/` is generated; don't edit it by hand):

```bash
python3 dsh-forge-theme/build.py
```

The flame logo is the same pair of 24-unit SVG paths in three places: the web
UI mark (`dsh-forge-theme/client.template.js`), the splash emblem
(`src/splash.html`, scaled 9×), and the app icon (`macos/make_icon.py`). Change
all three together. The splash and icon are built into the app, so rerun
`./macos/install.sh --build` after changing them.
