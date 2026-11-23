#!/bin/zsh
# Signs Marina for your iPhone with your free Apple ID and installs it, over
# the cable or over Wi-Fi once "Show this iPhone when on Wi-Fi" is on in
# Finder. (A free Apple ID's signature only installs from a connected Mac,
# never from a link.) Free signatures last 7 days: run this again when the
# app stops opening. Needs Xcode signed in to that Apple ID.
set -euo pipefail
cd "$(dirname "$0")"

TEAM="${TEAM:-W88AXK3MNB}"            # jacobmatthews08@icloud.com's personal team
DEVICE="${DEVICE:-00008140-001474890247001C}"   # Jacob's iPhone 16

xcodegen generate --quiet
rm -rf build/ota
xcodebuild -project Marina.xcodeproj -scheme Marina -configuration Release \
  -sdk iphoneos -destination 'generic/platform=iOS' \
  -derivedDataPath build/ota/derived -archivePath build/ota/Marina.xcarchive \
  DEVELOPMENT_TEAM="$TEAM" CODE_SIGN_STYLE=Automatic \
  -allowProvisioningUpdates archive | tail -2

cat > build/ota/export.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>method</key><string>debugging</string>
  <key>teamID</key><string>$TEAM</string>
  <key>signingStyle</key><string>automatic</string>
  <key>compileBitcode</key><false/>
  <key>thinning</key><string>&lt;none&gt;</string>
</dict></plist>
EOF
xcodebuild -exportArchive -archivePath build/ota/Marina.xcarchive \
  -exportOptionsPlist build/ota/export.plist -exportPath build/ota/out \
  -allowProvisioningUpdates | tail -2

ipa=build/ota/out/Marina.ipa
[[ -f "$ipa" ]] || { echo "No IPA came out of the export." >&2; exit 1; }
xcrun devicectl device install app --device "$DEVICE" "$ipa" | grep -E "installationURL|rror" || true
echo "Installed. The signature lasts 7 days."
