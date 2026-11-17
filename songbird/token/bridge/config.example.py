# ====================================================================
#  Songbird approval token - BRIDGE config (runs on lab3).
#  SECRET_HEX must be IDENTICAL to the device's config.
# ====================================================================

MQTT_BROKER = "homelab.tail35b6c6.ts.net"   # Funnel endpoint (use from Kali / off-LAN)
MQTT_PORT   = 10000
MQTT_USER   = "token-bridge"
MQTT_PASS   = "change-me"
MQTT_TLS    = True

REQ_TOPIC  = "songbird/token/req"
RESP_TOPIC = "songbird/token/resp"

# Same 32-byte secret as the device:
#   python3 -c "import secrets; print(secrets.token_hex(32))"
SECRET_HEX = "REPLACE_WITH_64_HEX_CHARS"

APPROVE_TIMEOUT_S = 35        # a touch longer than the device's own timeout

# Commands that may run WITHOUT a press. EXACT string match only - no
# wildcards, no patterns. Leave empty to require a physical press for
# everything (the safe default). Only add commands you have personally
# vetted as safe to let the model run unattended, scoped to your own lab.
ALLOWLIST = [
    # "nmap -sn 10.10.10.0/24",
]

import os as _os
BROKER_CERT = _os.path.join(_os.path.dirname(__file__), "..", "certs", "broker.crt")
