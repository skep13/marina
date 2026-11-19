#!/bin/zsh
# Builds an unsigned Marina.ipa for Sideloadly, which signs it with your free
# Apple ID when it installs it. Needs Xcode (not just the command line tools)
# and XcodeGen (brew install xcodegen).
#
#   ./build-ipa.sh            -> dist/Marina.ipa
#   ./build-ipa.sh --sim      -> builds and runs it in the iPhone simulator
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -f ../app/models/model.vrm ]]; then
  echo "app/models/model.vrm is missing: it's the avatar the Mac app uses, and the iPhone app bundles the same file." >&2
  exit 1
fi
if [[ ! -f ../app/renderer/vendor/vrm-bundle.js ]]; then
  echo "app/renderer/vendor/vrm-bundle.js is missing: run ./setup-mac.sh (or ./build-app.sh) once to build it." >&2
  exit 1
fi

xcodegen generate --quiet

if [[ "${1:-}" == "--sim" ]]; then
  device="${SIM_DEVICE:-iPhone 16}"
  xcodebuild -project Marina.xcodeproj -scheme Marina -configuration Debug \
    -destination "platform=iOS Simulator,name=$device" -derivedDataPath build/sim \
    build | tail -3
  app=build/sim/Build/Products/Debug-iphonesimulator/Marina.app
  xcrun simctl boot "$device" 2>/dev/null || true
  open -a Simulator
  xcrun simctl install "$device" "$app"
  xcrun simctl launch "$device" com.skep13.marina
  echo "Running in the $device simulator."
  exit 0
fi

rm -rf build/device dist
xcodebuild -project Marina.xcodeproj -scheme Marina -configuration Release \
  -sdk iphoneos -destination 'generic/platform=iOS' -derivedDataPath build/device \
  CODE_SIGNING_ALLOWED=NO CODE_SIGNING_REQUIRED=NO CODE_SIGN_IDENTITY="" \
  build | tail -3

mkdir -p dist/Payload
cp -R build/device/Build/Products/Release-iphoneos/Marina.app dist/Payload/
(cd dist && zip -qry Marina.ipa Payload && rm -rf Payload)
echo "Done: ios/dist/Marina.ipa ($(du -h dist/Marina.ipa | cut -f1)). Drag it into Sideloadly."
