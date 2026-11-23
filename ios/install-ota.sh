#!/bin/zsh
# Signs Marina for your iPhone with your free Apple ID and puts it on lab3,
# so the phone can install it from a link, no cable:
#   https://lab3.tail35b6c6.ts.net:8443   (tailnet only; open in Safari)
#
# Needs Xcode signed in to the Apple ID the phone is registered with
# (Xcode > Settings > Accounts). Free-account signatures last 7 days, so run
# this again and reinstall from the link when the app stops opening.
set -euo pipefail
cd "$(dirname "$0")"

TEAM="${TEAM:-W88AXK3MNB}"            # jacobmatthews08@icloud.com's personal team
LAB3="${LAB3:-root@192.168.1.13}"
DIR=/srv/marina-install

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
scp -q "$ipa" "$LAB3:$DIR/Marina.ipa"
ssh "$LAB3" "chmod 644 $DIR/Marina.ipa"
echo "Ready: open https://lab3.tail35b6c6.ts.net:8443 in Safari on the iPhone and tap Install."
