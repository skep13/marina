#!/bin/bash
# Install Forge.app on macOS: build the Rust binary, wrap it in a native .app
# bundle with an icon, and add it to the Dock. Idempotent — safe to re-run
# after a rebuild.
#
#   ./macos/install.sh            # build (if needed), install, add to Dock
#   ./macos/install.sh --no-dock  # install without touching the Dock
#   ./macos/install.sh --build    # force a fresh `cargo build --release`
#   ./macos/install.sh --uninstall
#
# Forge itself (DeepSeek Harness + config) lives in ~/.forge; this only
# installs the window that runs it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

APP="$HOME/Applications/Forge.app"
BUNDLE_ID="com.skep13.forge"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' "$PROJECT_DIR/Cargo.toml" | head -1)"

ADD_TO_DOCK=1
FORCE_BUILD=0
UNINSTALL=0
for arg in "$@"; do
  case "$arg" in
    --no-dock)   ADD_TO_DOCK=0 ;;
    --build)     FORCE_BUILD=1 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help)   sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

remove_from_dock() {
  if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "Forge.app"; then
    /usr/bin/python3 - <<'PY'
import subprocess, plistlib
raw = subprocess.run(["defaults", "export", "com.apple.dock", "-"], capture_output=True).stdout
pl = plistlib.loads(raw)
apps = pl.get("persistent-apps", [])
pl["persistent-apps"] = [a for a in apps if "Forge.app" not in
    a.get("tile-data", {}).get("file-data", {}).get("_CFURLString", "")]
subprocess.run(["defaults", "import", "com.apple.dock", "-"], input=plistlib.dumps(pl))
PY
    killall Dock 2>/dev/null || true
    echo "removed from Dock"
  fi
}

if [ "$UNINSTALL" = "1" ]; then
  echo "removing $APP"
  rm -rf "$APP"
  remove_from_dock
  echo "done (~/.forge left in place)"
  exit 0
fi

# --- 1. build -------------------------------------------------------------
BIN_SRC="$PROJECT_DIR/target/release/forge-app"
if [ "$FORCE_BUILD" = "1" ] || [ ! -x "$BIN_SRC" ]; then
  command -v cargo >/dev/null 2>&1 || { echo "error: cargo not found (brew install rust)" >&2; exit 1; }
  echo "building release binary…"
  ( cd "$PROJECT_DIR" && cargo build --release )
fi

# --- 2. app bundle --------------------------------------------------------
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
install -m 0755 "$BIN_SRC" "$APP/Contents/MacOS/Forge"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Forge</string>
  <key>CFBundleDisplayName</key><string>Forge</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>Forge</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleIconFile</key><string>Forge</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSLocalNetworkUsageDescription</key>
  <string>Forge connects to the coding model running on lab3 over your local network.</string>
  <key>NSAppTransportSecurity</key>
  <dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict>
</plist>
PLIST
echo "built app bundle -> $APP"

# --- 3. icon (best effort) ------------------------------------------------
if command -v iconutil >/dev/null 2>&1 && /usr/bin/python3 -c 'import PIL' >/dev/null 2>&1; then
  TMP="$(mktemp -d)"
  /usr/bin/python3 "$SCRIPT_DIR/make_icon.py" "$TMP/Forge.iconset" >/dev/null
  iconutil -c icns "$TMP/Forge.iconset" -o "$APP/Contents/Resources/Forge.icns"
  rm -rf "$TMP"
  echo "generated icon"
else
  echo "note: skipped icon (need python3 + Pillow and iconutil)"
fi

# --- 4. sign ad-hoc + register with LaunchServices ------------------------
codesign --force --deep --sign - "$APP" >/dev/null 2>&1 && echo "signed (ad-hoc)" || true
touch "$APP" "$APP/Contents/Info.plist"
LSREG="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
[ -x "$LSREG" ] && "$LSREG" -f "$APP" 2>/dev/null || true

# --- 5. Dock --------------------------------------------------------------
if [ "$ADD_TO_DOCK" = "1" ]; then
  if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "Forge.app"; then
    echo "already in Dock"
  else
    defaults write com.apple.dock persistent-apps -array-add \
      "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>$APP/</string><key>_CFURLStringType</key><integer>0</integer></dict><key>file-label</key><string>Forge</string></dict></dict>"
    killall Dock 2>/dev/null || true
    echo "added to Dock"
  fi
else
  echo "skipped Dock (--no-dock)"
fi

echo "done — open Forge from the Dock or ~/Applications"
