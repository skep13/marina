#!/bin/bash
# Install + start the Songbird Kali agent on the Kali box (ct113).
# Expects /tmp/kali_agent.py, /tmp/broker.crt, /tmp/songbird-kali-agent.service.
set -e
mkdir -p /opt/songbird-kali
cp /tmp/kali_agent.py /tmp/broker.crt /opt/songbird-kali/
pip install --quiet --break-system-packages paho-mqtt 2>/dev/null \
  || pip install --quiet paho-mqtt 2>/dev/null \
  || pipx install paho-mqtt 2>/dev/null || true
python3 -c "import paho.mqtt.client; print('paho OK')"
cp /tmp/songbird-kali-agent.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now songbird-kali-agent
sleep 2
echo "service: $(systemctl is-active songbird-kali-agent)"
journalctl -u songbird-kali-agent -n 6 --no-pager
