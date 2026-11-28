#!/usr/bin/env bash
# Builds the Linux app (deb + AppImage, x64) into linux/dist. The renderer and
# her model are copied in from app/ so both apps draw her the same way.
# The model can't be shared publicly (VRoid item licences): the packages are
# for your own machines only, and dist/ never goes in git.
set -euo pipefail
cd "$(dirname "$0")"
[[ -f ../app/renderer/vendor/vrm-bundle.js ]] || { echo "app/renderer/vendor/vrm-bundle.js is missing: run ./setup-mac.sh once." >&2; exit 1; }
[[ -f ../app/models/model.vrm ]] || { echo "app/models/model.vrm is missing." >&2; exit 1; }
rm -rf renderer models build && mkdir -p models build
cp -R ../app/renderer renderer
rm -rf renderer/screen-chat renderer/web-shim.js
cp ../app/models/model.vrm models/model.vrm
[[ -f ../app/models/mocap.bin ]] && cp ../app/models/mocap.bin models/mocap.bin || echo "No app/models/mocap.bin (node app/tools/mocap-build.mjs): procedural animations only." >&2
cp ../app/build/icon.png build/icon.png
[[ -d node_modules ]] || npm install --no-audit --no-fund
npx electron-builder --linux "${@:---x64}"
ls -la dist/*.deb dist/*.AppImage
