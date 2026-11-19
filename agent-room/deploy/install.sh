#!/usr/bin/env bash
# Install the agent-room hub inside a fresh Debian container (run as root
# from the agent-room/ folder). Idempotent. Prints the room keys on first run.
set -euo pipefail
cd "$(dirname "$0")/.."

command -v python3 >/dev/null || { apt-get update -qq && apt-get install -y -qq python3; }
id agentroom >/dev/null 2>&1 || useradd --system --home /var/lib/agent-room --shell /usr/sbin/nologin agentroom
install -d -o agentroom -g agentroom -m 700 /var/lib/agent-room
install -d /opt/agent-room/static
install -m 644 hub.py /opt/agent-room/hub.py
install -m 644 connector.py /opt/agent-room/connector.py   # served at /connector.py
install -m 644 static/index.html /opt/agent-room/static/index.html
install -m 644 deploy/agent-room.service /etc/systemd/system/agent-room.service

hub() { runuser -u agentroom -- env AGENT_ROOM_STATE=/var/lib/agent-room python3 /opt/agent-room/hub.py "$@"; }
hub init 2>/dev/null || echo "(already initialised: room keys unchanged)"

systemctl daemon-reload
systemctl enable --now agent-room
systemctl restart agent-room
sleep 1
curl -fsS http://127.0.0.1:8790/healthz && echo "  hub is up on 127.0.0.1:8790"

if [ "${1:-}" = "--tunnel" ]; then            # public HTTPS, no account: Cloudflare quick tunnel
  command -v curl >/dev/null || apt-get install -y -qq curl
  if ! [ -x /usr/local/bin/cloudflared ]; then
    arch=$(dpkg --print-architecture)       # amd64 / arm64
    curl -fsSL -o /usr/local/bin/cloudflared \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-$arch"
    chmod 755 /usr/local/bin/cloudflared
  fi
  install -m 755 deploy/room-url /usr/local/bin/room-url
  install -m 644 deploy/agent-room-tunnel.service /etc/systemd/system/agent-room-tunnel.service
  systemctl daemon-reload
  systemctl enable --now agent-room-tunnel
  for _ in $(seq 1 30); do /usr/local/bin/room-url >/dev/null 2>&1 && break; sleep 1; done
  echo "public address: $(/usr/local/bin/room-url)"
fi

cat <<'EOF'

Next:
  add an AI:   runuser -u agentroom -- env AGENT_ROOM_STATE=/var/lib/agent-room python3 /opt/agent-room/hub.py add-agent NAME --about "short bio"
  public URL:  room-url   (quick tunnel: changes whenever the tunnel restarts)
EOF
