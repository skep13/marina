#!/usr/bin/env bash
# Turn lab3 into a standalone, portable AI appliance.
#
# Plug any device into lab3's wired port and it gets an IP by DHCP, finds the
# box at http://ai.local, and reaches the web chat (Open WebUI) and the model
# API (OpenAI-compatible) with no setup. The agent for Marina/Songbird is one
# curl away. lab3 runs it all locally (model in ct110, chat in ct100).
#
# Run this ON the lab3 Proxmox host, as root.
#
#   setup-lab3.sh stage-a      # reversible: install + configure, no network change
#                              #   (safe to run now while lab3 is still on your LAN)
#   setup-lab3.sh cutover            # repurpose the wired NIC into the appliance
#                                    #   network. Cuts lab3 off your LAN / ends SSH.
#   setup-lab3.sh cutover --remote   # same, but ARM an auto-rollback first, so a
#                                    #   headless/remote cutover can't lock you out:
#                                    #   reverts to the LAN in ROLLBACK_WINDOW seconds
#                                    #   (default 600) unless you run 'confirm'. Run it
#                                    #   detached, e.g. via systemd-run (see README).
#   setup-lab3.sh wifi-ap            # host a Wi-Fi network (SSID in AP_SSID) so
#                                    #   devices connect with no cable. Put the WPA2
#                                    #   passphrase in /etc/appliance/ap.pass first.
#                                    #   Keeps the wired LAN up — no cutover needed.
#                                    #   Also shares the wired internet with Wi-Fi clients.
#   setup-lab3.sh wifi-both          # host "Local AI Box" AND join another Wi-Fi
#                                    #   (phone hotspot, etc.) on the same card, sharing
#                                    #   its internet. Networks go in /etc/appliance/uplink.conf.
#                                    #   Auto-reverts in WIFI_REVERT_WINDOW seconds unless
#                                    #   you run 'wifi-both-ok'. Run it detached (see README).
#   setup-lab3.sh wifi-both-ok       # keep wifi-both; cancel its auto-revert
#   setup-lab3.sh wifi-ap-only       # back to just hosting "Local AI Box"
#   setup-lab3.sh share-internet     # (re)apply just the internet sharing (NAT)
#   setup-lab3.sh roam               # for a box that gets moved around: the wired port
#                                    #   takes an address (and internet) from whatever it's
#                                    #   plugged into: a Mac sharing its Wi-Fi, a router.
#                                    #   A laptop on the cable always finds it at http://ai.local
#                                    #   (or ${WIRED_LL}), with no DHCP anywhere needed.
#   setup-lab3.sh tailscale          # join your Tailscale network, so devices reach
#                                    #   the box at http://lab3 from any network
#   setup-lab3.sh phone              # Marina's own app (with calls) for phones on
#                                    #   "Local AI Box", at https://10.42.0.1:8443. Copy the
#                                    #   app into ct110 first (see README). Phones trust the
#                                    #   box's certificate once: http://10.42.0.1/marina-ca.crt
#   setup-lab3.sh confirm            # keep the cutover; cancel the auto-rollback.
#   setup-lab3.sh status             # show what's configured / running
#
# Everything is idempotent; re-running is safe.
set -euo pipefail

# ---- settings ---------------------------------------------------------------
APPLIANCE_NAME="ai.local"       # mDNS name devices use
APPLIANCE_IP="10.42.0.1"        # lab3 on the appliance network
APPLIANCE_CIDR="10.42.0.1/24"
DHCP_FROM="10.42.0.50"
DHCP_TO="10.42.0.200"
BRIDGE="vmbr0"                  # the bridge on the wired NIC (nic0)

WEBUI_CTID=100                  # Open WebUI container (cloned from lab1 ct112)
WEBUI_IP_NOW="192.168.1.17"     # its address today, on your LAN
WEBUI_IP_APPLIANCE="10.42.0.11" # its address after cutover
MODEL_CTID=110                  # marina-brain: llama-swap (:8080) + Marina bridge (:8765)
MODEL_IP_NOW="192.168.1.15"
MODEL_IP_APPLIANCE="10.42.0.10"

KEY_FILE="/etc/appliance/lab3.key"   # llama-swap API key, injected by the proxy so
                                     # plugged-in apps need no key (isolated network)

# Wi-Fi access point: devices join this network instead of plugging in a cable.
AP_IFACE="wls1"                 # the wifi NIC (Intel AX200, AP mode)
AP_SSID="Local AI Box"          # network name
AP_CHANNEL=6                    # 2.4GHz (most reliable for AX200 AP)
AP_COUNTRY=GB
AP_PASS_FILE="/etc/appliance/ap.pass"   # WPA2 passphrase (>=8 chars); NOT in the repo
# wifi-both: the same card also joins another network for internet (client + AP at once).
AP_VIF="wlap0"                  # virtual interface that hosts the AP in wifi-both mode
UPLINK_CONF="/etc/appliance/uplink.conf"   # wpa_supplicant network={} blocks; NOT in the repo
WIRED_NIC="nic0"                # the physical port under ${BRIDGE}
WIFI_REVERT_WINDOW=600          # seconds before an unconfirmed wifi-both reverts
# roam: the wired port wherever lab3 is plugged in.
WAN_IF="wan0"                   # a second interface on ${BRIDGE} that takes an address by DHCP
WIRED_LL="169.254.42.1"         # fixed link-local address: a laptop on the cable reaches the box
                                #   at this with nothing else on the wire (macOS self-assigns 169.254.x)
CT_NET="${MODEL_IP_NOW%.*}.0/24" # the containers' network on ${BRIDGE}
# Who may use Marina and the keyless model API through the proxy: the box's Wi-Fi,
# a laptop on the cable (link-local, or a Mac's Internet Sharing, 192.168.2-3.x),
# the home LAN and Tailscale. Anywhere else the box is plugged in gets a 403.
TRUSTED_NETS="${APPLIANCE_IP%.*}.0/24 169.254.0.0/16 192.168.2.0/23 ${CT_NET} 100.64.0.0/10 127.0.0.1/8"
TS_NAME="lab3"                  # Tailscale device name: reach the box from anywhere at http://lab3
# phone: Marina's app over HTTPS (browsers only allow the mic on HTTPS), Wi-Fi clients only.
PHONE_PORT=8443
PHONE_NET="10.42.0.0/24"        # who may open it: devices on "Local AI Box"
PHONE_TOKEN_FILE="/etc/appliance/phone.token"   # the proxy's key to her bridge; NOT in the repo
MARINA_CONFIG="/var/lib/marina/character_config.yaml"   # inside the model container
CADDY_CA="/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt"
LOG() { echo "[appliance] $*"; }

need_root() { [ "$(id -u)" = 0 ] || { echo "run as root on the lab3 host"; exit 1; }; }

# ---- the proxy: one friendly address for chat + API -------------------------
write_caddyfile() {  # $1 = webui ip, $2 = model ip
  local webui="$1" model="$2" key="" phone=""
  [ -f "$KEY_FILE" ] && key="$(cat "$KEY_FILE")"
  [ -f "$PHONE_TOKEN_FILE" ] && phone="$(cat "$PHONE_TOKEN_FILE")"
  install -d /etc/caddy
  cat > /etc/caddy/Caddyfile <<EOF
# Generated by appliance/setup-lab3.sh — do not edit by hand.
{
	admin off
	auto_https disable_redirects
}

# The appliance: http://${APPLIANCE_NAME} (and the raw IP) on port 80, plus
# http://${TS_NAME} for devices on your Tailscale network, from anywhere.
http://${APPLIANCE_NAME}, http://${APPLIANCE_IP}, http://${WIRED_LL}, http://localhost, http://${TS_NAME} {
	@untrusted not remote_ip ${TRUSTED_NETS}
	# OpenAI-compatible model API. The key is injected here so plugged-in
	# apps and the agent need none on the isolated network.
	handle /v1/* {
		respond @untrusted "Not from this network." 403
		reverse_proxy ${model}:8080 {
			$( [ -n "$key" ] && echo "header_up Authorization \"Bearer ${key}\"" )
		}
	}
	# Marina's bridge (chat/stream, voice, moods) for apps like the café game:
	# http://${APPLIANCE_NAME}/marina/health, /marina/chat/stream. Streams NDJSON.
	# Her bridge only opens to its own machine or a proxy with the key, so the key
	# goes on here, for trusted networks only.
	handle_path /marina/* {
		respond @untrusted "Not from this network." 403
		reverse_proxy ${model}:8765 {
			$( [ -n "$phone" ] && echo "header_up Authorization \"Bearer ${phone}\"" )
			flush_interval -1
		}
	}
	# Cybersecurity RAG retrieval (rag_serve.py on 127.0.0.1:7391); see rag/.
	handle /rag* {
		reverse_proxy 127.0.0.1:7391
	}
	# The box's certificate, for phones to trust once (see 'phone').
	handle /marina-ca.crt {
		root * /var/lib/appliance/www
		header Content-Type application/x-x509-ca-cert
		file_server
	}
	# One-line agent installer: curl http://${APPLIANCE_NAME}/install | sh
	handle /install {
		root * /var/lib/appliance/www
		rewrite * /install.sh
		file_server
	}
	# Everything else: the web chat.
	handle {
		reverse_proxy ${webui}:8080
	}
}
EOF
  [ -n "$phone" ] && cat >> /etc/caddy/Caddyfile <<EOF

# Marina's own app, calls included, for phones on "${AP_SSID}". HTTPS because
# browsers only give a page the microphone over HTTPS; the certificate is the
# box's own (tls internal). Only Wi-Fi clients get in, and the proxy hands her
# bridge the key it wants, so the bridge stays closed to everything else.
https://${APPLIANCE_IP}:${PHONE_PORT}, https://${APPLIANCE_NAME}:${PHONE_PORT} {
	tls internal
	@outside not remote_ip ${PHONE_NET}
	respond @outside "Join the ${AP_SSID} Wi-Fi to talk to Marina." 403
	reverse_proxy ${model}:8765 {
		header_up Authorization "Bearer ${phone}"
		flush_interval -1
	}
}
EOF
  caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
}

# ---- DHCP + mDNS on the wired port (dnsmasq) --------------------------------
write_dnsmasq() {
  install -d /etc/dnsmasq.d
  cat > /etc/dnsmasq.d/appliance.conf <<EOF
# Generated by appliance/setup-lab3.sh. Serves the appliance network on ${BRIDGE}.
interface=${BRIDGE}
bind-interfaces
dhcp-range=${DHCP_FROM},${DHCP_TO},12h
dhcp-option=option:router,${APPLIANCE_IP}
dhcp-option=option:dns-server,${APPLIANCE_IP}
# Resolve the appliance name (and anything.ai.local) to the box itself.
address=/${APPLIANCE_NAME}/${APPLIANCE_IP}
# Don't read /etc/resolv.conf's upstreams unless wifi provides one.
no-resolv
EOF
}

write_device_installer() {
  install -d /var/lib/appliance/www
  cat > /var/lib/appliance/www/install.sh <<EOF
#!/bin/sh
# Agent bootstrap for a device plugged into the appliance.
# Points the Marina/Songbird agent at the appliance API.
echo "Appliance API: http://${APPLIANCE_NAME}/v1  (models: marina, songbird)"
echo "Open the chat at: http://${APPLIANCE_NAME}"
echo "Set your agent/base URL to http://${APPLIANCE_NAME}/v1 — no API key needed here."
EOF
}

# ---- phone: Marina's app for phones on the box's Wi-Fi -----------------------
phone_setup() {
  need_root
  pct exec "$MODEL_CTID" -- test -f /opt/marina/app/renderer/index.html || {
    echo "Copy Marina's app into ct${MODEL_CTID} first: app/renderer, app/models/model.vrm and"
    echo "app/build/icon.png from the repo, under /opt/marina/app/ (see README)."; exit 1; }
  install -d -m 700 /etc/appliance
  [ -s "$PHONE_TOKEN_FILE" ] || { openssl rand -hex 24 > "$PHONE_TOKEN_FILE"; chmod 600 "$PHONE_TOKEN_FILE"; }
  local token; token="$(cat "$PHONE_TOKEN_FILE")"
  # Her bridge: serve the app, and let the proxy in with the token.
  if ! pct exec "$MODEL_CTID" -- grep -q '^web:' "$MARINA_CONFIG"; then
    pct exec "$MODEL_CTID" -- cp "$MARINA_CONFIG" "${MARINA_CONFIG}.bak-before-phone"
    printf '\n%s\n%s\n%s\n%s\n%s\n' \
      "# Her own app for phones on the box Wi-Fi (setup-lab3.sh phone). The proxy" \
      "# sends the token; without it the network only gets /shared/ and /v1/." \
      "web:" "  enabled: true" "  token: \"${token}\"" \
      | pct exec "$MODEL_CTID" -- sh -c "cat >> '${MARINA_CONFIG}'"
  elif ! pct exec "$MODEL_CTID" -- grep -qF "token: \"${token}\"" "$MARINA_CONFIG"; then
    echo "${MARINA_CONFIG} in ct${MODEL_CTID} already has a web: section. Put in it:"
    echo "  enabled: true"; echo "  token: (the contents of ${PHONE_TOKEN_FILE})"; exit 1
  fi
  pct exec "$MODEL_CTID" -- systemctl restart marina
  if [ -f "$CONFIRMED" ]; then write_caddyfile "$WEBUI_IP_APPLIANCE" "$MODEL_IP_APPLIANCE"; else write_caddyfile "$WEBUI_IP_NOW" "$MODEL_IP_NOW"; fi
  systemctl restart caddy
  for _ in $(seq 1 20); do [ -f "$CADDY_CA" ] && break; sleep 1; done
  install -d /var/lib/appliance/www
  install -m 644 "$CADDY_CA" /var/lib/appliance/www/marina-ca.crt
  LOG "phone: join \"${AP_SSID}\", trust http://${APPLIANCE_IP}/marina-ca.crt once, then open https://${APPLIANCE_IP}:${PHONE_PORT}"
}

# ---- stages -----------------------------------------------------------------
stage_a() {
  need_root
  LOG "Stage A (reversible): install + configure, no network change."
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  # caddy from the official repo
  if ! command -v caddy >/dev/null; then
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https curl gnupg
    curl -fsSL https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    echo "deb [signed-by=/usr/share/keyrings/caddy-stable-archive-keyring.gpg] https://dl.cloudsmith.io/public/caddy/stable/deb/debian any-version main" > /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq
  fi
  apt-get install -y -qq dnsmasq avahi-daemon caddy

  # dnsmasq must NOT run yet — it would fight your LAN's DHCP. Stage it disabled.
  systemctl disable --now dnsmasq 2>/dev/null || true
  write_dnsmasq

  # Proxy + mDNS can run now, pointing at today's LAN addresses (testable:
  # hit http://<lab3-ip> and you get the chat). Re-pointed at cutover.
  install -d /etc/appliance
  write_caddyfile "$WEBUI_IP_NOW" "$MODEL_IP_NOW"
  write_device_installer
  systemctl enable --now avahi-daemon
  systemctl enable --now caddy
  systemctl reload caddy || systemctl restart caddy
  LOG "Stage A done. Test now: http://$(hostname -I | awk '{print $1}')/ should show the chat."
  LOG "dnsmasq is installed but OFF until cutover. Nothing on your LAN changed."
}

ROLLBACK_WINDOW="${ROLLBACK_WINDOW:-600}"   # seconds to confirm before auto-revert
PRECUTOVER="/etc/appliance/interfaces.precutover"
CONFIRMED="/etc/appliance/cutover-confirmed"

cutover() {
  need_root
  # --remote (or non-tty) arms an auto-rollback so a headless/remote cutover
  # can't lock you out: if you don't `confirm` within the window, it reverts
  # to the LAN and SSH comes back. Safe to run over SSH detached.
  local remote=0; [ "${2:-}" = "--remote" ] && remote=1
  cat <<EOF

  !!  CUTOVER — reconfigures ${BRIDGE} into the appliance network.
  !!  It CUTS lab3 OFF YOUR LAN and ENDS this SSH session (expected).
  !!  lab3 must already have LEFT the Proxmox cluster (see README).
  $( [ "$remote" = 1 ] && echo "!!  Remote mode: auto-reverts in ${ROLLBACK_WINDOW}s unless you run 'setup-lab3.sh confirm'." )

EOF
  if [ "$remote" != 1 ]; then
    read -rp "Type CUTOVER to proceed: " c; [ "$c" = CUTOVER ] || { echo "aborted"; exit 1; }
  fi

  # Save what we need to revert to, and (remote) arm the rollback BEFORE any change.
  install -d /etc/appliance
  cp /etc/network/interfaces "$PRECUTOVER"
  rm -f "$CONFIRMED"
  pct config "$MODEL_CTID" | sed -n 's/^net0: //p' > /etc/appliance/ct${MODEL_CTID}.net0.pre
  pct config "$WEBUI_CTID" | sed -n 's/^net0: //p' > /etc/appliance/ct${WEBUI_CTID}.net0.pre
  if [ "$remote" = 1 ]; then
    systemctl stop appliance-rollback.timer 2>/dev/null || true
    systemd-run --on-active="${ROLLBACK_WINDOW}" --unit=appliance-rollback \
      /root/setup-lab3.sh _rollback >/dev/null 2>&1 || \
      LOG "WARNING: could not arm auto-rollback (systemd-run failed) — proceeding WITHOUT a safety net"
    LOG "auto-rollback armed: reverts in ${ROLLBACK_WINDOW}s unless you run 'setup-lab3.sh confirm'"
  fi

  # 1. Re-address the bridge to the appliance network (no gateway: it's its own net).
  cp /etc/network/interfaces /etc/network/interfaces.bak.$(date +%s)
  LOG "rewriting ${BRIDGE} to ${APPLIANCE_CIDR} in /etc/network/interfaces (backup saved)"
  python3 - "$BRIDGE" "$APPLIANCE_CIDR" <<'PY'
import re, sys
f="/etc/network/interfaces"; br,cidr=sys.argv[1],sys.argv[2]
t=open(f).read()
blk=re.search(rf"(iface {br} inet static.*?)(?=\n(?:auto|iface|source|$))", t, re.S)
new=f"iface {br} inet static\n\taddress {cidr}\n\tbridge-ports nic0\n\tbridge-stp off\n\tbridge-fd 0\n"
t=t[:blk.start()]+new+t[blk.end():] if blk else t+"\n"+new
open(f,"w").write(t)
PY

  # 2. Move the containers onto the appliance subnet.
  pct set "$MODEL_CTID" --net0 name=eth0,bridge=${BRIDGE},ip=${MODEL_IP_APPLIANCE}/24
  pct set "$WEBUI_CTID" --net0 name=eth0,bridge=${BRIDGE},ip=${WEBUI_IP_APPLIANCE}/24

  # 3. Point the proxy at the new container IPs and the WebUI at the new model IP.
  write_caddyfile "$WEBUI_IP_APPLIANCE" "$MODEL_IP_APPLIANCE"
  pct exec "$WEBUI_CTID" -- sh -lc "sed -i 's#${MODEL_IP_NOW}#${MODEL_IP_APPLIANCE}#g' /etc/open-webui.env" || true

  # 4. Turn on DHCP/mDNS for plugged-in devices.
  systemctl enable --now dnsmasq

  # 5. Apply networking (this is the point of no remote return).
  ifreload -a || systemctl restart networking
  pct reboot "$MODEL_CTID"; pct reboot "$WEBUI_CTID"
  systemctl restart caddy
  LOG "Cutover applied. Plug a device into the wired port; it gets an IP and reaches http://${APPLIANCE_NAME}."
  if systemctl is-active appliance-rollback.timer >/dev/null 2>&1; then
    LOG "CONFIRM within the window: from a device plugged into the appliance, SSH ${APPLIANCE_IP} and run 'setup-lab3.sh confirm' — else it auto-reverts to the LAN."
  fi
}

share_internet() {  # NAT Wi-Fi clients out of whatever uplink lab3 has (the wired
                    # port, or the Wi-Fi it joined in wifi-both mode), so joining the
                    # box's Wi-Fi doesn't cost a laptop its internet. $1 = the AP interface
  local ap="${1:-$(systemctl is-enabled appliance-wlap >/dev/null 2>&1 && echo "$AP_VIF" || echo "$AP_IFACE")}"
  cat > /etc/sysctl.d/90-appliance-forward.conf <<EOF
net.ipv4.ip_forward=1
EOF
  sysctl -q -p /etc/sysctl.d/90-appliance-forward.conf
  install -d /etc/appliance
  cat > /etc/appliance/nat.nft <<EOF
table ip appliance_nat {
	chain postrouting {
		type nat hook postrouting priority srcnat; policy accept;
		ip saddr ${APPLIANCE_IP%.*}.0/24 oifname != { "${ap}", "lo" } masquerade
		# the containers, when lab3's uplink isn't the home LAN they sit on
		ip saddr ${CT_NET} oifname != { "${BRIDGE}", "${ap}", "lo" } masquerade
	}
}
EOF
  cat > /etc/systemd/system/appliance-nat.service <<EOF
[Unit]
Description=Share lab3's internet with appliance Wi-Fi clients
After=network-online.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=-/usr/sbin/nft delete table ip appliance_nat
ExecStart=/usr/sbin/nft -f /etc/appliance/nat.nft
ExecStop=-/usr/sbin/nft delete table ip appliance_nat
[Install]
WantedBy=multi-user.target
EOF
  command -v nft >/dev/null || { export DEBIAN_FRONTEND=noninteractive; apt-get install -y -qq nftables; }
  systemctl daemon-reload
  systemctl enable --now appliance-nat
  systemctl restart appliance-nat
  LOG "internet sharing on: Wi-Fi clients reach the internet through whichever uplink lab3 has"
}

wifi_ap() {   # host a Wi-Fi network so devices connect with no cable
  need_root
  if systemctl is-enabled appliance-wlap >/dev/null 2>&1; then echo "wifi-both is on; run 'wifi-ap-only' first to go back to plain AP mode"; exit 1; fi
  [ -f "$AP_PASS_FILE" ] || { echo "put the WPA2 passphrase (>=8 chars) in $AP_PASS_FILE first"; exit 1; }
  local pass; pass="$(cat "$AP_PASS_FILE")"
  command -v hostapd >/dev/null || { export DEBIAN_FRONTEND=noninteractive; apt-get install -y -qq iw hostapd; }
  rfkill unblock wifi 2>/dev/null || true
  iw reg set "$AP_COUNTRY" 2>/dev/null || true
  cat > /etc/hostapd/hostapd.conf <<EOF
interface=${AP_IFACE}
driver=nl80211
ssid=${AP_SSID}
country_code=${AP_COUNTRY}
hw_mode=g
channel=${AP_CHANNEL}
ieee80211n=1
wmm_enabled=1
auth_algs=1
wpa=2
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
wpa_passphrase=${pass}
EOF
  chmod 600 /etc/hostapd/hostapd.conf
  sed -i 's|^#*DAEMON_CONF=.*|DAEMON_CONF="/etc/hostapd/hostapd.conf"|' /etc/default/hostapd
  grep -q DAEMON_CONF /etc/default/hostapd || echo 'DAEMON_CONF="/etc/hostapd/hostapd.conf"' >> /etc/default/hostapd
  # give the AP interface the appliance IP, after hostapd brings the radio up
  cat > /etc/systemd/system/appliance-ap-ip.service <<EOF
[Unit]
Description=Appliance AP IP on ${AP_IFACE}
After=hostapd.service
BindsTo=hostapd.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/sbin/ip addr replace ${APPLIANCE_IP}/24 dev ${AP_IFACE}
ExecStart=/sbin/ip link set ${AP_IFACE} up
[Install]
WantedBy=multi-user.target
EOF
  # DHCP + mDNS for AP clients (on the wifi interface, not the LAN)
  cat > /etc/dnsmasq.d/appliance.conf <<EOF
interface=${AP_IFACE}
bind-interfaces
dhcp-range=${DHCP_FROM},${DHCP_TO},12h
dhcp-option=option:router,${APPLIANCE_IP}
dhcp-option=option:dns-server,${APPLIANCE_IP}
address=/${APPLIANCE_NAME}/${APPLIANCE_IP}
# Other names go to lab3's own upstream DNS, so AP clients keep internet
# whenever the wired port has one (see share_internet below).
resolv-file=/etc/resolv.conf
EOF
  share_internet
  # refresh the proxy too, so new routes (like /marina/) go live with this command
  if [ -f "$CONFIRMED" ]; then write_caddyfile "$WEBUI_IP_APPLIANCE" "$MODEL_IP_APPLIANCE"; else write_caddyfile "$WEBUI_IP_NOW" "$MODEL_IP_NOW"; fi
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
  mkdir -p /etc/systemd/system/dnsmasq.service.d
  printf '[Unit]\nAfter=appliance-ap-ip.service\nRequires=appliance-ap-ip.service\n' \
    > /etc/systemd/system/dnsmasq.service.d/after-ap.conf
  systemctl daemon-reload
  systemctl unmask hostapd 2>/dev/null || true
  systemctl enable hostapd appliance-ap-ip dnsmasq
  systemctl restart hostapd; sleep 4; systemctl restart appliance-ap-ip; systemctl restart dnsmasq
  LOG "Wi-Fi AP '${AP_SSID}' up on ${AP_IFACE} ($(systemctl is-active hostapd)); join it and open http://${APPLIANCE_NAME}"
}

tailscale_setup() {  # reach the box from any network over Tailscale (needs internet here)
  need_root
  command -v tailscale >/dev/null || curl -fsSL https://tailscale.com/install.sh | sh
  systemctl enable --now tailscaled
  # the proxy answers to http://${TS_NAME} too (chat, /v1, /marina/)
  if [ -f "$CONFIRMED" ]; then write_caddyfile "$WEBUI_IP_APPLIANCE" "$MODEL_IP_APPLIANCE"; else write_caddyfile "$WEBUI_IP_NOW" "$MODEL_IP_NOW"; fi
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
  # prints a login link the first time: open it and sign in to add the box to your tailnet
  tailscale up --hostname="${TS_NAME}"
  LOG "Tailscale up as '${TS_NAME}' ($(tailscale ip -4 2>/dev/null | head -1)). From a device on your tailnet: http://${TS_NAME}/marina/health"
}

# ---- the uplink watcher (wifi-both and roam) ---------------------------------
# Points lab3's route + DNS at whichever uplink is live, best first: the home LAN
# on the cable, then whatever else the cable is plugged into (a Mac sharing its
# internet, another router), then the Wi-Fi it joined. In wifi-both mode it also
# keeps "Local AI Box" on that Wi-Fi's channel.
write_watcher() {
  local lan_gw; lan_gw="$(awk -v br="$BRIDGE" '$1=="iface"{f=($2==br)} f&&$1=="gateway"{print $2; exit}' /etc/network/interfaces)"
  cat > /usr/local/sbin/appliance-uplink-watch <<EOF
#!/bin/bash
# Generated by appliance/setup-lab3.sh. Route + DNS follow the live uplink;
# "Local AI Box" follows the Wi-Fi uplink's channel (wifi-both).
UP=${AP_IFACE} AP=${AP_VIF} BR=${BRIDGE} WIRED=${WIRED_NIC} WAN=${WAN_IF} LAN_GW=${lan_gw}
HCONF=/etc/hostapd/hostapd.conf UPCONF=${UPLINK_CONF}
mkdir -p /run/appliance; [ -f /run/appliance/resolv.conf ] || cp /etc/resolv.conf /run/appliance/resolv.conf
f2c() { echo \$(( (\$1 - 2407) / 5 )); }
ap_chan() { awk -F= '/^channel=/{print \$2}' "\$HCONF"; }
set_chan() {
  logger -t appliance "moving the AP to channel \$1 to match the uplink"
  sed -i "s/^channel=.*/channel=\$1/" "\$HCONF"
  systemctl restart hostapd; sleep 3; systemctl restart appliance-ap-ip dnsmasq
}
known() { sed -n 's/^[[:space:]]*ssid="\(.*\)"[[:space:]]*\$/\1/p' "\$UPCONF" 2>/dev/null; }
cable() { [ "\$(cat /sys/class/net/\$WIRED/carrier 2>/dev/null)" = 1 ]; }
lost=0 noip=0
while sleep 10; do
  if [ -e /sys/class/net/\$AP ] && systemctl -q is-active appliance-uplink 2>/dev/null; then
    freq=\$(iw dev "\$UP" link 2>/dev/null | awk '/freq:/{print int(\$2)}')
    if [ -n "\$freq" ]; then
      lost=0
      # joined but no IPv4 for 30s: dhclient gave up while the hotspot was away
      # and sleeps through the rejoin, so make it ask again now
      if ip -4 addr show dev "\$UP" | grep -q inet; then noip=0; else noip=\$((noip + 1)); fi
      if [ \$noip -ge 3 ] && systemctl -q is-active appliance-uplink-dhcp; then
        logger -t appliance "joined the uplink but no address; asking again"
        systemctl restart appliance-uplink-dhcp; noip=0
      fi
      if [ "\$freq" -lt 2500 ] && [ "\$(f2c "\$freq")" != "\$(ap_chan)" ]; then set_chan "\$(f2c "\$freq")"; fi
    else
      lost=\$((lost + 1))
      # the client can't join a network on another channel while the AP is up,
      # so if a known network is in range elsewhere, move the AP to it first
      if [ \$lost -ge 2 ]; then
        best=\$(wpa_cli -i "\$UP" scan_results 2>/dev/null | awk -F'\t' 'NR>1 && \$2<2500 {print \$3"\t"\$2"\t"\$5}' | sort -rn |
          while IFS=\$'\t' read -r sig fr ssid; do known | grep -qxF "\$ssid" && { echo "\$fr"; break; }; done)
        if [ -n "\$best" ] && [ "\$(f2c "\$best")" != "\$(ap_chan)" ]; then set_chan "\$(f2c "\$best")"; lost=0; fi
        wpa_cli -i "\$UP" scan >/dev/null 2>&1
      fi
    fi
  fi
  wan_gw=\$(cat /run/appliance/wan-gw 2>/dev/null)
  if cable && [ -n "\$LAN_GW" ] && ping -c1 -W1 -I "\$BR" "\$LAN_GW" >/dev/null 2>&1; then
    ip route del default dev "\$WAN" 2>/dev/null
    ip route replace default via "\$LAN_GW" dev "\$BR" 2>/dev/null; src=/etc/resolv.conf
  elif cable && [ -n "\$wan_gw" ] && [ -e /sys/class/net/\$WAN ] && ping -c1 -W1 -I "\$WAN" "\$wan_gw" >/dev/null 2>&1; then
    ip route del default dev "\$BR" 2>/dev/null
    ip route replace default via "\$wan_gw" dev "\$WAN" 2>/dev/null; src=/run/appliance/wan-resolv.conf
  else
    ip route del default dev "\$BR" 2>/dev/null; ip route del default dev "\$WAN" 2>/dev/null
    src=/run/appliance/uplink-resolv.conf
  fi
  [ -s "\$src" ] && ! cmp -s "\$src" /run/appliance/resolv.conf && cp "\$src" /run/appliance/resolv.conf
done
EOF
  chmod 755 /usr/local/sbin/appliance-uplink-watch
  cat > /etc/systemd/system/appliance-uplink-watch.service <<EOF
[Unit]
Description=Route + DNS via the live uplink; AP on the Wi-Fi uplink's channel
After=network-online.target hostapd.service appliance-uplink.service appliance-wan.service
[Service]
ExecStart=/usr/local/sbin/appliance-uplink-watch
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
}

# ---- roam: a box that gets plugged in somewhere different every time ---------
# The wired port keeps its home address (${BRIDGE}), and a second interface on it
# (${WAN_IF}) takes an address from whatever's on the other end: a Mac with
# Internet Sharing on, a router, nothing. It also has a fixed link-local address,
# so a laptop on the cable finds the box even when nobody hands out addresses.
# mDNS answers "${APPLIANCE_NAME}" on each network with the box's address there.
roam() {
  need_root
  command -v dhclient >/dev/null || { echo "needs isc-dhcp-client (dhclient)"; exit 1; }
  install -d /etc/appliance /run/appliance
  local lan_gw host_ip
  lan_gw="$(awk -v br="$BRIDGE" '$1=="iface"{f=($2==br)} f&&$1=="gateway"{print $2; exit}' /etc/network/interfaces)"
  host_ip="$(awk -v br="$BRIDGE" '$1=="iface"{f=($2==br)} f&&$1=="address"{print $2; exit}' /etc/network/interfaces)"; host_ip="${host_ip%/*}"
  [ -n "$host_ip" ] || { echo "no static address on ${BRIDGE} in /etc/network/interfaces"; exit 1; }
  # a stable MAC, so the box gets the same address back from the same Mac/router
  local mac wmac; mac="$(cat /sys/class/net/${WIRED_NIC}/address)"
  wmac="$(printf '%02x' $(( (0x${mac%%:*} | 2) ^ 8 )))${mac#??}"
  cat > /etc/systemd/system/appliance-wan.service <<EOF
[Unit]
Description=Wired port: take an address from whatever lab3 is plugged into (${WAN_IF})
After=network.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=-/sbin/ip link del ${WAN_IF}
ExecStart=/sbin/ip link add ${WAN_IF} link ${BRIDGE} address ${wmac} type macvlan mode bridge
ExecStart=/sbin/ip addr add ${WIRED_LL}/16 dev ${WAN_IF} label ${WAN_IF}:ll
ExecStart=/sbin/ip link set ${WAN_IF} up
ExecStop=-/sbin/ip link del ${WAN_IF}
[Install]
WantedBy=multi-user.target
EOF
  printf 'timeout 20;\nretry 10;\n' > /etc/appliance/dhclient-uplink.conf
  cat > /etc/systemd/system/appliance-wan-dhcp.service <<EOF
[Unit]
Description=DHCP on the wired port (${WAN_IF})
After=appliance-wan.service
BindsTo=appliance-wan.service
[Service]
ExecStart=$(command -v dhclient) -d -cf /etc/appliance/dhclient-uplink.conf -pf /run/dhclient-wan.pid -lf /var/lib/dhcp/dhclient.${WAN_IF}.leases ${WAN_IF}
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
  # dhclient stays off /etc/resolv.conf and the routes (Proxmox owns the first,
  # the watcher the second); it leaves the gateway and DNS for the watcher.
  # On the home LAN it's left alone: ${BRIDGE} already has that.
  install -d /etc/dhcp/dhclient-enter-hooks.d
  cat > /etc/dhcp/dhclient-enter-hooks.d/appliance-wan <<EOF
if [ "\$interface" = "${WAN_IF}" ]; then
  make_resolv_conf() { :; }
  mkdir -p /run/appliance
  case "\$reason" in
    BOUND|RENEW|REBIND|REBOOT)
      if [ "\${new_routers%% *}" = "${lan_gw}" ]; then rm -f /run/appliance/wan-gw
      else
        printf '%s\n' "\${new_routers%% *}" > /run/appliance/wan-gw
        [ -n "\$new_domain_name_servers" ] && printf 'nameserver %s\n' \$new_domain_name_servers > /run/appliance/wan-resolv.conf
      fi ;;
    EXPIRE|FAIL|RELEASE|STOP) rm -f /run/appliance/wan-gw ;;
  esac
  new_routers=""
fi
true  # a failing enter hook makes dhclient-script throw the lease away
EOF
  # the containers go out through lab3, so they follow it to whichever uplink is live
  local ct cur; for ct in "$MODEL_CTID" "$WEBUI_CTID"; do
    cur="$(pct config "$ct" | sed -n 's/^net0: //p')"
    [ -f /etc/appliance/ct${ct}.net0.pre-roam ] || echo "$cur" > /etc/appliance/ct${ct}.net0.pre-roam
    case "$cur" in *"gw=${host_ip},"*) ;; *) pct set "$ct" --net0 "$(echo "$cur" | sed "s/gw=[^,]*/gw=${host_ip}/")" ;; esac
    # and ask lab3 for names, which forwards to whichever uplink is live
    pct config "$ct" | grep -q "^nameserver: ${host_ip}\$" || pct set "$ct" --nameserver "$host_ip"
  done
  local dm=/etc/dnsmasq.d/appliance.conf
  [ -f "$dm" ] && { grep -qx "listen-address=${host_ip}" "$dm" || echo "listen-address=${host_ip}" >> "$dm"; }
  # mDNS: the box itself answers "${APPLIANCE_NAME}", with its address on each
  # network (the cable, the AP), instead of one fixed address for everyone
  local conf=/etc/avahi/avahi-daemon.conf
  [ -f "$conf.pre-roam" ] || cp -a "$conf" "$conf.pre-roam"
  sed -i '/^host-name=/d; /^allow-interfaces=/d' "$conf"
  sed -i "/^\[server\]/a host-name=${APPLIANCE_NAME%.local}\nallow-interfaces=${AP_IFACE},${AP_VIF},${WAN_IF}" "$conf"
  [ -f /etc/avahi/hosts ] && sed -i "/[[:space:]]${APPLIANCE_NAME}\$/d; /[[:space:]]ai\.box\.local\$/d" /etc/avahi/hosts
  share_internet
  write_watcher
  if [ -f "$CONFIRMED" ]; then write_caddyfile "$WEBUI_IP_APPLIANCE" "$MODEL_IP_APPLIANCE"; else write_caddyfile "$WEBUI_IP_NOW" "$MODEL_IP_NOW"; fi
  systemctl daemon-reload
  systemctl enable appliance-wan appliance-wan-dhcp appliance-uplink-watch >/dev/null
  systemctl restart appliance-wan appliance-wan-dhcp appliance-uplink-watch
  systemctl restart avahi-daemon
  systemctl restart dnsmasq 2>/dev/null || true
  systemctl reload caddy 2>/dev/null || systemctl restart caddy
  LOG "roam on. A laptop on the cable: http://${APPLIANCE_NAME} (or http://${WIRED_LL}). Internet comes from whatever the cable's plugged into, else the Wi-Fi uplink."
}

# ---- wifi-both: host the AP and join another network on one card -------------
# The AX200 can be a client and an AP at the same time, but only on ONE channel,
# and only on 2.4 GHz for the AP. So: the client joins a 2.4 GHz network from
# uplink.conf, and a watcher moves "Local AI Box" onto that network's channel
# (AP clients drop for a few seconds when it moves). With no known network in
# range, the AP just stays where it is.
WIFI_PRE="/etc/appliance/pre-wifi-both"
WIFI_OK="/etc/appliance/wifi-both.ok"

wifi_both() {
  need_root
  [ -f "$AP_PASS_FILE" ] || { echo "run wifi-ap first (needs $AP_PASS_FILE)"; exit 1; }
  [ -s "$UPLINK_CONF" ] || { cat <<EOF
Put the network(s) to join in $UPLINK_CONF first, e.g.:

network={
    ssid="My iPhone"
    psk="hotspot password"
}

(2.4 GHz only. On an iPhone hotspot turn on "Maximise Compatibility".)
EOF
    exit 1; }
  chmod 600 "$UPLINK_CONF"
  # every tool must already be here: with no uplink yet there's no apt
  local missing=""
  for t in iw hostapd wpa_supplicant wpa_cli dhclient nft; do command -v "$t" >/dev/null || missing+=" $t"; done
  if [ -n "$missing" ]; then
    if timeout 5 bash -c 'exec 3<>/dev/tcp/deb.debian.org/80' 2>/dev/null; then
      export DEBIAN_FRONTEND=noninteractive; apt-get install -y -qq iw hostapd wpasupplicant isc-dhcp-client nftables
    else echo "missing:$missing — and no internet to install them. Cable or USB-tether lab3 once, then re-run."; exit 1; fi
  fi
  local phy; phy="$(basename "$(readlink -f /sys/class/net/${AP_IFACE}/phy80211)")"
  iw phy "$phy" info | grep -A8 'valid interface combinations' | grep -q 'AP' \
    || { echo "${AP_IFACE} (${phy}) doesn't report AP + client together; not changing anything"; exit 1; }

  # remember the AP-only setup once, so revert has something to go back to
  if [ ! -d "$WIFI_PRE" ]; then
    install -d -m 700 "$WIFI_PRE"
    cp -a /etc/hostapd/hostapd.conf /etc/dnsmasq.d/appliance.conf /etc/systemd/system/appliance-ap-ip.service /etc/appliance/nat.nft "$WIFI_PRE"/ 2>/dev/null || true
  fi
  rm -f "$WIFI_OK"

  # the AP moves to a virtual interface with its own (locally administered) MAC
  local mac vmac; mac="$(cat /sys/class/net/${AP_IFACE}/address)"
  vmac="$(printf '%02x' $(( (0x${mac%%:*} | 2) ^ 4 )))${mac#??}"
  cat > /etc/systemd/system/appliance-wlap.service <<EOF
[Unit]
Description=Virtual AP interface ${AP_VIF} on ${AP_IFACE}
Before=hostapd.service appliance-uplink.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStartPre=-/usr/sbin/iw dev ${AP_VIF} del
ExecStart=/usr/sbin/iw dev ${AP_IFACE} interface add ${AP_VIF} type __ap
ExecStart=/sbin/ip link set ${AP_VIF} address ${vmac}
ExecStop=-/usr/sbin/iw dev ${AP_VIF} del
[Install]
WantedBy=multi-user.target
EOF
  mkdir -p /etc/systemd/system/hostapd.service.d
  printf '[Unit]\nRequires=appliance-wlap.service\nAfter=appliance-wlap.service\n' > /etc/systemd/system/hostapd.service.d/wlap.conf
  sed -i "s/^interface=.*/interface=${AP_VIF}/" /etc/hostapd/hostapd.conf
  sed -i "s/ dev ${AP_IFACE}\$/ dev ${AP_VIF}/; s/link set ${AP_IFACE} up/link set ${AP_VIF} up/; s/IP on ${AP_IFACE}/IP on ${AP_VIF}/" /etc/systemd/system/appliance-ap-ip.service
  # forward Wi-Fi clients' lookups to whichever uplink is live (an older setup had no-resolv)
  sed -i "s/^interface=.*/interface=${AP_VIF}/; /^no-resolv\$/d; /^resolv-file=/d" /etc/dnsmasq.d/appliance.conf
  echo "resolv-file=/run/appliance/resolv.conf" >> /etc/dnsmasq.d/appliance.conf

  # the client side: wpa_supplicant (2.4 GHz only) + DHCP at a low-priority route
  { echo "ctrl_interface=/run/wpa_supplicant"; echo "country=${AP_COUNTRY}"; echo "ap_scan=1"
    echo "freq_list=2412 2417 2422 2427 2432 2437 2442 2447 2452 2457 2462 2467 2472"
    cat "$UPLINK_CONF"; } > /etc/appliance/wpa-uplink.conf
  chmod 600 /etc/appliance/wpa-uplink.conf
  cat > /etc/systemd/system/appliance-uplink.service <<EOF
[Unit]
Description=Join an uplink Wi-Fi on ${AP_IFACE} (wifi-both)
After=appliance-wlap.service hostapd.service
[Service]
ExecStart=$(command -v wpa_supplicant) -i ${AP_IFACE} -D nl80211 -c /etc/appliance/wpa-uplink.conf
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
  cat > /etc/systemd/system/appliance-uplink-dhcp.service <<EOF
[Unit]
Description=DHCP on the uplink Wi-Fi ${AP_IFACE} (wifi-both)
After=appliance-uplink.service
BindsTo=appliance-uplink.service
[Service]
Environment=IF_METRIC=600
ExecStart=$(command -v dhclient) -d -cf /etc/appliance/dhclient-uplink.conf -pf /run/dhclient-uplink.pid ${AP_IFACE}
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
EOF
  # keep asking every 10s: a hotspot often appears after dhclient starts, and its
  # default is to give up for 5 minutes
  printf 'timeout 20;\nretry 10;\n' > /etc/appliance/dhclient-uplink.conf
  # keep dhclient off /etc/resolv.conf (Proxmox owns it); save the uplink's DNS for dnsmasq
  install -d /etc/dhcp/dhclient-enter-hooks.d
  cat > /etc/dhcp/dhclient-enter-hooks.d/appliance-uplink <<EOF
if [ "\$interface" = "${AP_IFACE}" ]; then
  make_resolv_conf() { :; }
  mkdir -p /run/appliance
  if [ -n "\$new_domain_name_servers" ]; then printf 'nameserver %s\n' \$new_domain_name_servers > /run/appliance/uplink-resolv.conf; fi
fi
true  # a failing enter hook makes dhclient-script throw the lease away
EOF

  write_watcher
  cat > /etc/sysctl.d/91-appliance-uplink.conf <<EOF
net.ipv4.conf.all.ignore_routes_with_linkdown=1
EOF
  sysctl -q -p /etc/sysctl.d/91-appliance-uplink.conf
  install -d /run/appliance; cp /etc/resolv.conf /run/appliance/resolv.conf

  # arm the auto-revert before touching the live radio: if you can't get back
  # on "Local AI Box" to run 'wifi-both-ok', it puts the AP-only setup back
  systemctl stop appliance-wifi-revert.timer 2>/dev/null || true
  systemctl reset-failed 'appliance-wifi-revert*' 2>/dev/null || true
  systemd-run --unit=appliance-wifi-revert --on-active="${WIFI_REVERT_WINDOW}" "$(readlink -f "$0")" _wifi_revert >/dev/null
  LOG "auto-revert armed: ${WIFI_REVERT_WINDOW}s unless you run '$0 wifi-both-ok'"

  share_internet "$AP_VIF"
  systemctl daemon-reload
  systemctl stop hostapd 2>/dev/null || true
  systemctl enable appliance-wlap appliance-uplink appliance-uplink-dhcp appliance-uplink-watch >/dev/null
  systemctl restart appliance-wlap
  # the AP's address moves to ${AP_VIF}; left on ${AP_IFACE} too it shadows the route to Wi-Fi clients
  ip addr del "${APPLIANCE_CIDR}" dev "${AP_IFACE}" 2>/dev/null || true
  systemctl restart hostapd; sleep 4; systemctl restart appliance-ap-ip dnsmasq
  systemctl restart appliance-uplink appliance-uplink-dhcp appliance-uplink-watch

  # beaconing = the interface is in AP mode with the SSID set (hostapd_cli needs
  # a ctrl_interface, which hostapd.conf here doesn't have)
  ap_up() { iw dev "$AP_VIF" info 2>/dev/null | grep -q 'type AP' && iw dev "$AP_VIF" info | grep -qF "ssid ${AP_SSID}"; }
  local _; for _ in $(seq 1 15); do ap_up && break; sleep 2; done
  if ! ap_up; then
    LOG "the AP didn't come up on ${AP_VIF}; reverting now"; _wifi_revert; exit 1
  fi
  LOG "'${AP_SSID}' is up on ${AP_VIF}; ${AP_IFACE} is joining a network from ${UPLINK_CONF}."
  LOG "Rejoin '${AP_SSID}', check you have internet, then: ssh root@${APPLIANCE_IP} '$0 wifi-both-ok'"
}

wifi_both_ok() {
  need_root
  touch "$WIFI_OK"
  systemctl stop appliance-wifi-revert.timer 2>/dev/null || true
  systemctl reset-failed 'appliance-wifi-revert*' 2>/dev/null || true
  LOG "wifi-both kept. Uplink: $(iw dev "$AP_IFACE" link 2>/dev/null | awk -F': ' '/SSID/{print $2}' || echo 'none yet')"
}

_wifi_revert() {  # back to hosting the AP on the card itself, no uplink
  need_root
  if [ -f "$WIFI_OK" ] && [ "${1:-}" != "--force" ]; then LOG "wifi-both confirmed; not reverting"; return 0; fi
  [ -d "$WIFI_PRE" ] || { LOG "nothing saved to revert to"; return 1; }
  LOG "reverting to AP-only on ${AP_IFACE}"
  systemctl disable --now appliance-uplink-watch appliance-uplink-dhcp appliance-uplink 2>/dev/null || true
  systemctl stop hostapd 2>/dev/null || true
  systemctl disable --now appliance-wlap 2>/dev/null || true
  iw dev "$AP_VIF" del 2>/dev/null || true
  rm -f /etc/systemd/system/hostapd.service.d/wlap.conf /etc/dhcp/dhclient-enter-hooks.d/appliance-uplink "$WIFI_OK"
  cp -a "$WIFI_PRE"/hostapd.conf /etc/hostapd/ 2>/dev/null || true
  cp -a "$WIFI_PRE"/appliance.conf /etc/dnsmasq.d/ 2>/dev/null || true
  cp -a "$WIFI_PRE"/appliance-ap-ip.service /etc/systemd/system/ 2>/dev/null || true
  cp -a "$WIFI_PRE"/nat.nft /etc/appliance/ 2>/dev/null || true
  systemctl daemon-reload
  systemctl restart appliance-nat 2>/dev/null || true
  systemctl restart hostapd; sleep 4; systemctl restart appliance-ap-ip dnsmasq
  ip route show default | grep -q " dev ${BRIDGE}" || { gw="$(awk -v br="$BRIDGE" '$1=="iface"{f=($2==br)} f&&$1=="gateway"{print $2; exit}' /etc/network/interfaces)"; [ -n "$gw" ] && ip route replace default via "$gw" dev "$BRIDGE"; }
  LOG "AP-only again: '${AP_SSID}' on ${AP_IFACE} ($(systemctl is-active hostapd))"
}

confirm() {   # keep the cutover; cancel the auto-rollback
  need_root
  touch "$CONFIRMED"
  systemctl stop appliance-rollback.timer 2>/dev/null || true
  systemctl reset-failed 'appliance-rollback*' 2>/dev/null || true
  LOG "Cutover confirmed. Auto-rollback cancelled; the appliance network is permanent."
}

_rollback() {  # fired by the armed timer; reverts unless confirmed
  need_root
  if [ -f "$CONFIRMED" ]; then LOG "rollback: confirmed, nothing to do"; exit 0; fi
  LOG "rollback: not confirmed in time — restoring the LAN config"
  [ -f "$PRECUTOVER" ] && cp "$PRECUTOVER" /etc/network/interfaces
  [ -f /etc/appliance/ct${MODEL_CTID}.net0.pre ] && pct set "$MODEL_CTID" --net0 "$(cat /etc/appliance/ct${MODEL_CTID}.net0.pre)"
  [ -f /etc/appliance/ct${WEBUI_CTID}.net0.pre ] && pct set "$WEBUI_CTID" --net0 "$(cat /etc/appliance/ct${WEBUI_CTID}.net0.pre)"
  systemctl disable --now dnsmasq 2>/dev/null || true
  write_caddyfile "$WEBUI_IP_NOW" "$MODEL_IP_NOW"; systemctl restart caddy 2>/dev/null || true
  ifreload -a 2>/dev/null || systemctl restart networking
  pct reboot "$MODEL_CTID" 2>/dev/null || true; pct reboot "$WEBUI_CTID" 2>/dev/null || true
  LOG "rollback done — lab3 is back on the LAN; SSH should return."
}

status() {
  echo "caddy:    $(systemctl is-active caddy 2>/dev/null)"
  echo "avahi:    $(systemctl is-active avahi-daemon 2>/dev/null)"
  echo "dnsmasq:  $(systemctl is-active dnsmasq 2>/dev/null) (off until cutover)"
  echo "${BRIDGE}: $(ip -br addr show "$BRIDGE" 2>/dev/null | awk '{print $3}')"
  echo "hostapd:  $(systemctl is-active hostapd 2>/dev/null) on $(awk -F= '/^interface=/{print $2}' /etc/hostapd/hostapd.conf 2>/dev/null), channel $(awk -F= '/^channel=/{print $2}' /etc/hostapd/hostapd.conf 2>/dev/null)"
  echo "uplink:   $(systemctl is-active appliance-uplink 2>/dev/null) $(iw dev "$AP_IFACE" link 2>/dev/null | awk -F': ' '/SSID/{print "joined " $2}')$([ -f "$WIFI_OK" ] && echo ' (kept)')"
  echo "cable:    $(cat /sys/class/net/${WIRED_NIC}/carrier 2>/dev/null | sed 's/1/plugged in/; s/0/unplugged/')$(ip -br -4 addr show "$WAN_IF" 2>/dev/null | awk '{$1=$2=""; print ", " $0}')"
  echo "route:    $(ip route show default 2>/dev/null | head -1)"
  echo "webui ct${WEBUI_CTID}: $(pct status "$WEBUI_CTID" 2>/dev/null)"
  echo "model ct${MODEL_CTID}: $(pct status "$MODEL_CTID" 2>/dev/null)"
}

case "${1:-}" in
  stage-a)   stage_a ;;
  wifi-ap)   wifi_ap ;;
  wifi-both) wifi_both ;;
  wifi-both-ok) wifi_both_ok ;;
  wifi-ap-only) _wifi_revert --force ;;
  _wifi_revert) _wifi_revert ;;
  share-internet) need_root; share_internet ;;
  roam)      roam ;;
  tailscale) tailscale_setup ;;
  phone)     phone_setup ;;
  cutover)   cutover "$@" ;;
  confirm)   confirm ;;
  _rollback) _rollback ;;
  status)    status ;;
  *) sed -n '2,42p' "$0"; exit 2 ;;
esac
