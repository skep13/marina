#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
ROOT="$(pwd)"

if [ ! -d .venv ]; then
  echo "No .venv here. Run ./setup-mac.sh first." >&2
  exit 1
fi

echo "==> Rebuilding the renderer vendor bundle"
( cd app && npx esbuild src/vendor-entry.js --bundle --format=esm \
    --outfile=renderer/vendor/vrm-bundle.js --log-level=warning )

echo "==> Recording project root: $ROOT"
mkdir -p app/build
printf '%s' "$ROOT" > app/build/project-root.txt

echo "==> Packaging"
( cd app && npx electron-builder --mac --dir )

APP="app/dist/mac-arm64/Marina.app"

echo "==> Signing (ad-hoc, so macOS can remember microphone permission)"
xattr -cr "$APP"
codesign --force --deep --sign - "$APP" 2>/dev/null || true
xattr -cr "$APP"

echo "==> Installing to /Applications"
rm -rf /Applications/Marina.app
cp -R "$APP" /Applications/Marina.app
xattr -cr /Applications/Marina.app

echo
echo "Done. Marina.app is in /Applications."
echo "Open it once, then right-click its Dock icon -> Options -> Keep in Dock."
