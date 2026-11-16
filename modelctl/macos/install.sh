#!/bin/bash
# Install modelctl on macOS: build the binary, wrap it in a .app that opens the
# TUI in Terminal, generate an icon, and add it to the Dock. Idempotent — safe
# to re-run after a rebuild.
#
#   ./macos/install.sh            # build (if needed), install, add to Dock
#   ./macos/install.sh --no-dock  # install without touching the Dock
#   ./macos/install.sh --build    # force a fresh `cargo build --release`
#   ./macos/install.sh --uninstall
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

BIN_DST="$HOME/.local/bin/modelctl"
APP="$HOME/Applications/modelctl.app"
BUNDLE_ID="com.skep13.modelctl"

ADD_TO_DOCK=1
FORCE_BUILD=0
for arg in "$@"; do
  case "$arg" in
    --no-dock)   ADD_TO_DOCK=0 ;;
    --build)     FORCE_BUILD=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help)   sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

uninstall() {
  echo "removing $APP and $BIN_DST"
  rm -rf "$APP"
  rm -f "$BIN_DST"
  if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "modelctl.app"; then
    /usr/bin/python3 - "$HOME" <<'PY'
import subprocess, sys, plistlib
home = sys.argv[1]
raw = subprocess.run(["defaults", "export", "com.apple.dock", "-"],
                     capture_output=True).stdout
pl = plistlib.loads(raw)
apps = pl.get("persistent-apps", [])
kept = [a for a in apps if "modelctl.app" not in
        a.get("tile-data", {}).get("file-data", {}).get("_CFURLString", "")]
pl["persistent-apps"] = kept
subprocess.run(["defaults", "import", "com.apple.dock", "-"],
               input=plistlib.dumps(pl))
PY
    killall Dock 2>/dev/null || true
    echo "removed from Dock"
  fi
  echo "done"
}

if [ "${UNINSTALL:-0}" = "1" ]; then
  uninstall
  exit 0
fi

# --- 1. build -------------------------------------------------------------
BIN_SRC="$PROJECT_DIR/target/release/modelctl"
if [ "$FORCE_BUILD" = "1" ] || [ ! -x "$BIN_SRC" ]; then
  if ! command -v cargo >/dev/null 2>&1; then
    echo "error: cargo not found and no release binary at $BIN_SRC" >&2
    echo "install Rust (e.g. 'brew install rust') or run with a prebuilt binary." >&2
    exit 1
  fi
  echo "building release binary…"
  ( cd "$PROJECT_DIR" && cargo build --release )
fi

# --- 2. install binary ----------------------------------------------------
mkdir -p "$HOME/.local/bin" "$HOME/Applications"
install -m 0755 "$BIN_SRC" "$BIN_DST"
echo "installed binary -> $BIN_DST"

# --- 3. build the .app bundle --------------------------------------------
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>modelctl</string>
  <key>CFBundleDisplayName</key><string>modelctl</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleVersion</key><string>0.1.0</string>
  <key>CFBundleShortVersionString</key><string>0.1.0</string>
  <key>CFBundleExecutable</key><string>modelctl-launch</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>modelctl</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

cat > "$APP/Contents/MacOS/modelctl-launch" <<'SH'
#!/bin/bash
# Open the modelctl TUI in a Terminal window.
BIN="$HOME/.local/bin/modelctl"
if [ ! -x "$BIN" ]; then
  osascript -e 'display alert "modelctl not found" message "Expected the binary at ~/.local/bin/modelctl. Re-run macos/install.sh."'
  exit 1
fi
exec /usr/bin/open -a Terminal "$BIN"
SH
chmod +x "$APP/Contents/MacOS/modelctl-launch"
echo "built app bundle -> $APP"

# --- 4. icon (best effort) ------------------------------------------------
if command -v iconutil >/dev/null 2>&1 && \
   /usr/bin/python3 -c 'import PIL' >/dev/null 2>&1; then
  ICONSET="$(mktemp -d)/modelctl.iconset"
  /usr/bin/python3 "$SCRIPT_DIR/make_icon.py" "$ICONSET" >/dev/null
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/modelctl.icns"
  rm -rf "$(dirname "$ICONSET")"
  echo "generated icon"
else
  echo "note: skipped icon (need python3 + Pillow and iconutil); app uses the generic icon"
fi

# --- 5. register with LaunchServices -------------------------------------
touch "$APP" "$APP/Contents/Info.plist"
LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREG" ] && "$LSREG" -f "$APP" 2>/dev/null || true

# --- 6. add to Dock -------------------------------------------------------
if [ "$ADD_TO_DOCK" = "1" ]; then
  if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "modelctl.app"; then
    echo "already in Dock"
  else
    defaults write com.apple.dock persistent-apps -array-add \
      "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP/</string><key>_CFURLStringType</key><integer>0</integer></dict><key>file-label</key><string>modelctl</string></dict></dict>"
    killall Dock 2>/dev/null || true
    echo "added to Dock"
  fi
else
  echo "skipped Dock (--no-dock)"
fi

echo "done — launch modelctl from the Dock, or run 'modelctl' if ~/.local/bin is on your PATH"
