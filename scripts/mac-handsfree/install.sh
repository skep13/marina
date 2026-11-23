#!/bin/zsh
# Starts hands-free Marina at login and keeps it running.
# Off:  launchctl bootout gui/$(id -u)/com.marina.handsfree
set -e
cd "$(dirname "$0")"
command -v SwitchAudioSource >/dev/null || brew install switchaudio-osx
dst=~/Library/LaunchAgents/com.marina.handsfree.plist
sed "s#\$HOME#$HOME#g" com.marina.handsfree.plist > "$dst"
launchctl bootout gui/$(id -u)/com.marina.handsfree 2>/dev/null || true
launchctl bootstrap gui/$(id -u) "$dst"
echo "Running. Log: ~/Library/Logs/marina-handsfree.log"
