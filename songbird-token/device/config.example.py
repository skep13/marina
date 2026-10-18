# ====================================================================
#  Songbird approval token - DEVICE config.  Fill in the blanks.
#  SECRET_HEX must be IDENTICAL to the bridge's config.
# ====================================================================

# --- Wi-Fi (your phone hotspot). 2.4 GHz only - on iPhone turn on
#     "Maximize Compatibility" in the Personal Hotspot settings. ---
WIFI_SSID = "your-hotspot-name"
WIFI_PASS = "your-hotspot-password"

# --- MQTT broker (both the device and the bridge dial OUT to this) ---
MQTT_BROKER = "homelab.tail35b6c6.ts.net"
MQTT_PORT   = 10000                  # Tailscale Funnel public port -> broker 8883
MQTT_USER   = "token-device"
MQTT_PASS   = "change-me"
MQTT_TLS    = True                   # set False only for a plaintext broker on trusted LAN

REQ_TOPIC  = b"songbird/token/req"   # bridge -> device  (approval requests)
RESP_TOPIC = b"songbird/token/resp"  # device -> bridge  (signed decisions)

# --- Shared secret. Generate ONCE and paste the SAME value here and
#     in the bridge config:
#       python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_HEX = "REPLACE_WITH_64_HEX_CHARS"

# --- Behaviour ---
DEVICE_ID          = "songbird-token-1"
APPROVE_TIMEOUT_MS = 30000           # auto-DENY if not pressed within this long
MDNS_NAME          = "token"         # advertises as token.local (best-effort)
BROKER_CERT        = "broker.crt"    # broker's cert on the board, for TLS verification
MIN_VIEW_MS        = 2500            # button ignored this long so you can't blind-approve
