#!/bin/bash
# Builds "Rainy Day Café.app" and installs it in /Applications.
#   ./build-app.sh            build + install
#   ./build-app.sh --no-install
set -euo pipefail
cd "$(dirname "$0")"

NAME="Rainy Day Café"
APP="dist/$NAME.app"
rm -rf "$APP" build
mkdir -p build "$APP/Contents/MacOS" "$APP/Contents/Resources/game"

swiftc -O -o "$APP/Contents/MacOS/RainyDayCafe" mac/CafeApp.swift \
  -framework Cocoa -framework WebKit

swift mac/make-icon.swift build/AppIcon.iconset
iconutil -c icns build/AppIcon.iconset -o "$APP/Contents/Resources/AppIcon.icns"

cp index.html "$APP/Contents/Resources/game/"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Rainy Day Café</string>
  <key>CFBundleDisplayName</key><string>Rainy Day Café</string>
  <key>CFBundleIdentifier</key><string>com.skep13.rainydaycafe</string>
  <key>CFBundleExecutable</key><string>RainyDayCafe</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.simulation-games</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSAppTransportSecurity</key>
  <dict>
    <key>NSAllowsLocalNetworking</key><true/>
    <key>NSAllowsArbitraryLoads</key><true/>
  </dict>
  <key>NSLocalNetworkUsageDescription</key>
  <string>Talks to Marina's bridge so she can chat with you in the café.</string>
</dict>
</plist>
PLIST

codesign --force --deep --sign - "$APP" >/dev/null
echo "built $APP"

if [[ "${1:-}" != "--no-install" ]]; then
  rm -rf "/Applications/$NAME.app"
  cp -R "$APP" /Applications/
  echo "installed /Applications/$NAME.app"
fi
