#!/bin/sh
# sudo sh homelab/mac-routes/install.sh
set -e; cd "$(dirname "$0")"
install -d /usr/local/sbin
install -m755 home-lab-routes /usr/local/sbin/home-lab-routes
install -m644 com.skep13.home-lab-routes.plist /Library/LaunchDaemons/
launchctl bootout system/com.skep13.home-lab-routes 2>/dev/null || true
launchctl bootstrap system /Library/LaunchDaemons/com.skep13.home-lab-routes.plist
sleep 2; log show --last 1m --predicate 'process == "logger"' 2>/dev/null | grep home-lab-routes | tail -1
