# ====================================================================
#  Songbird display - DEVICE config. Copy to config.py and fill in.
# ====================================================================

WIFI_SSID = "your-ssid"
WIFI_PASS = "your-wifi-password"

# Broker on lab1. LAN for an on-network test; swap to the Funnel
# name (homelab.tail35b6c6.ts.net:10000) for the roaming/portable setup.
MQTT_BROKER = "homelab.tail35b6c6.ts.net"
MQTT_PORT   = 10000
MQTT_USER   = "token-device"
MQTT_PASS   = "your-mqtt-password"
MQTT_TLS    = True
BROKER_CERT = "broker.crt"

TOPIC       = b"songbird/display"
DEVICE_ID   = "songbird-display-1"
HOLD_S      = 30          # revert to the logo 30s after the last message
MDNS_NAME   = "songbird-display"
PUBLIC_DNS  = "8.8.8.8"    # resolve the broker via public DNS (hotspot DNS returns a wrong answer)
