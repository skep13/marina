#!/usr/bin/env bash
# Copies dot-bridge into container 114 on lab2 and (re)starts its services.
set -euo pipefail
cd "$(dirname "$0")"
NODE=root@192.168.1.11
CT=114

COPYFILE_DISABLE=1 tar --no-xattrs -czf - dot.pa dot_ear.py dot_call.py systemd | ssh "$NODE" "cat > /tmp/dot-bridge.tgz && pct push $CT /tmp/dot-bridge.tgz /tmp/dot-bridge.tgz"
ssh "$NODE" "pct exec $CT -- bash -s" <<'INNER'
set -e
mkdir -p /opt/dot-bridge && tar -xzf /tmp/dot-bridge.tgz -C /opt/dot-bridge
cp /opt/dot-bridge/systemd/*.service /etc/systemd/system/
if [ ! -f /root/.vnc/passwd ]; then
  mkdir -p /root/.vnc
  head -c 9 /dev/urandom | base64 | tr -d '/+=' | cut -c1-8 > /root/vnc-password
  x11vnc -storepasswd "$(cat /root/vnc-password)" /root/.vnc/passwd >/dev/null 2>&1
  chmod 600 /root/vnc-password /root/.vnc/passwd
fi
if [ ! -d /root/.android/avd/dot.avd ]; then
  echo no | ANDROID_SDK_ROOT=/opt/android /opt/android/cmdline-tools/latest/bin/avdmanager \
    create avd -n dot -k "system-images;android-34;google_apis_playstore;x86_64" -d pixel_4
  # The Alexa app needs room; the Drop In needs the mic allowed.
  printf 'disk.dataPartition.size=6G\nhw.audioInput=yes\nhw.audioOutput=yes\nhw.keyboard=yes\n' >> /root/.android/avd/dot.avd/config.ini
fi
systemctl daemon-reload
systemctl enable --now dot-audio dot-display dot-emulator
systemctl restart dot-audio dot-display dot-emulator
INNER
echo "Screen: http://192.168.1.248:6080/vnc.html"
