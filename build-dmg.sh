#!/usr/bin/env bash
# Builds one disk image with every Mac app in this repo:
#
#   Marina.app            the companion (app/, built by ./build-app.sh)
#   Forge.app             the coding agent window (forge-app/)
#   modelctl.app          lab3 model switcher TUI (modelctl/)
#   Rainy Day Café.app    the café game (cozy-cafe/)
#
# Output: dist/Marina-Suite-<date>.dmg, with an Applications shortcut to drag
# the apps onto.
#
#   ./build-dmg.sh               rebuild Forge, modelctl and the café; reuse
#                                Marina.app if it's newer than its source
#   ./build-dmg.sh --marina      also rebuild Marina (slow; installs it too)
#   ./build-dmg.sh --no-build    package whatever is already built
#
# Forge and modelctl are installed to ~/Applications by their own install
# scripts as part of the build; the Dock is left alone.
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

BUILD=1
BUILD_MARINA=0
for arg in "$@"; do
  case "$arg" in
    --marina)   BUILD_MARINA=1 ;;
    --no-build) BUILD=0 ;;
    -h|--help)  sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

MARINA_APP="$ROOT/app/dist/mac-arm64/Marina.app"
FORGE_APP="$HOME/Applications/Forge.app"
MODELCTL_APP="$HOME/Applications/modelctl.app"
CAFE_APP="$ROOT/cozy-cafe/dist/Rainy Day Café.app"

if [ "$BUILD" = 1 ]; then
  stale_marina=0
  if [ ! -d "$MARINA_APP" ] || [ -n "$(find app/src app/renderer app/main.js app/preload.js server \
        -newer "$MARINA_APP/Contents/Info.plist" -type f \
        -not -path '*/vendor/*' -not -path '*/.pytest_cache/*' -not -name '*.pyc' 2>/dev/null | head -1)" ]; then
    stale_marina=1
  fi
  if [ "$BUILD_MARINA" = 1 ] || [ "$stale_marina" = 1 ]; then
    echo "==> Marina"
    ./build-app.sh
  else
    echo "==> Marina: up to date, reusing $MARINA_APP"
  fi
  echo "==> Forge"
  ./forge-app/macos/install.sh --build --no-dock
  echo "==> modelctl"
  ./modelctl/macos/install.sh --build --no-dock
  echo "==> Rainy Day Café"
  ./cozy-cafe/build-app.sh --no-install
fi

for a in "$MARINA_APP" "$FORGE_APP" "$MODELCTL_APP" "$CAFE_APP"; do
  [ -d "$a" ] || { echo "missing: $a" >&2; exit 1; }
done

STAGE="$(mktemp -d)/Marina Suite"
trap 'rm -rf "$(dirname "$STAGE")"' EXIT
mkdir -p "$STAGE"

echo "==> Staging"
for a in "$MARINA_APP" "$FORGE_APP" "$MODELCTL_APP" "$CAFE_APP"; do
  ditto "$a" "$STAGE/$(basename "$a")"
done
# modelctl's installer doesn't sign its bundle; an unsigned app from a disk
# image is refused outright on Apple silicon, so sign any that lack one.
for a in "$STAGE"/*.app; do
  if ! codesign --verify --deep "$a" 2>/dev/null; then
    xattr -cr "$a"
    codesign --force --deep --sign - "$a"
    echo "    signed $(basename "$a") (ad-hoc)"
  fi
done
ln -s /Applications "$STAGE/Applications"
cat > "$STAGE/Read Me.txt" <<'EOF'
Marina Suite

Drag the apps onto Applications.

Marina.app            Self-contained: brings its own Python, voice and
                      Whisper model. Open it once, then keep it in the Dock.
Forge.app             Window for the Forge coding agent. Needs ~/.forge set
                      up (DeepSeek Harness, config, lab3 key), Node 24
                      (brew install node@24), lab3 on the network and your
                      YubiKey.
modelctl.app          Switches the model lab3 is serving. Opens in Terminal.
Rainy Day Café.app    The café game.

These are signed ad-hoc (or with a development identity), not notarised.
If macOS refuses to open one, right-click it and choose Open.
EOF

mkdir -p dist
DMG="dist/Marina-Suite-$(date +%Y-%m-%d).dmg"
rm -f "$DMG"
echo "==> Building $DMG"
hdiutil create -volname "Marina Suite" -srcfolder "$STAGE" -fs APFS \
  -format ULMO -ov "$DMG" >/dev/null
hdiutil verify "$DMG" >/dev/null && echo "    image verified"

echo
echo "Done: $DMG ($(du -h "$DMG" | cut -f1))"
