# Songbird approval token

A portable hardware gate for Songbird. The model can *propose and compose*
real actions, but anything not pre-vetted will not run until a human presses
the button on a physical token. The press is signed, so software — including a
fully compromised host — cannot forge an approval.

```
Songbird (lab3) → bridge.py → MQTT broker ← ESP32-S3 token (on your hotspot)
                     │            (both dial OUT — works through NAT both sides)
                     └── runs the command only after a valid signed press
```

The ESP32 and the bridge never connect to each other directly; they rendezvous
on a broker. **Only an opaque id + a short label cross the broker — the real
command never leaves lab3.**

## Hardware
- ESP32-S3 (8 MB PSRAM), MicroPython v1.29.0 (already flashed).
- 0.96" SSD1306 OLED on **I2C: SDA=GPIO8, SCL=GPIO9**, address 0x3C.
- Approval button: the onboard **BOOT** button (GPIO0).
- Power: USB from a power bank (portable) or any charger.

## Status — tested on 2026-10-18
- [x] OLED detected at 0x3C, draws correctly.
- [x] BOOT button read + debounce.
- [x] Approval screen + countdown + default-deny on timeout.
- [x] On-device HMAC-SHA256 matches host HMAC byte-for-byte (so the bridge
      will accept real presses and reject anything else).
- [ ] End-to-end over a broker — needs your broker + hotwifi creds (below).

## Deployed broker (set up 2026-10-18)

Mosquitto 2.0.21 runs in **lab1 / ct102 "tailscale"** (the dedicated Tailscale
LXC), with TLS + password auth. Two reach paths to the same broker:

| Path | Address | Used by |
|------|---------|---------|
| LAN  | `192.168.1.253:8883` | the bridge (on lab3) |
| Funnel | `homelab.tail35b6c6.ts.net:10000` | the roaming ESP32 |

- Users: `token-bridge` and `token-device` (passwords already in the configs).
- Self-signed cert in `/etc/mosquitto/certs/` on ct102; clients use `CERT_NONE`.
- Config: `/etc/mosquitto/conf.d/songbird.conf` on ct102.
- Validated: bridge <-> broker <-> signed approval executes; a forged
  signature is rejected and nothing runs.

### Remaining to go fully live
1. **Enable the Funnel** (public ingress - must be run by you). On lab1:
   ```bash
   pct exec 102 -- tailscale funnel --bg --tcp 10000 tcp://localhost:8883
   ```
   If it complains Funnel isn't allowed, enable it in the Tailscale admin
   console (Access Controls -> add the `funnel` node attribute for this node,
   and turn on HTTPS certificates), then rerun.
2. **Device Wi-Fi:** fill `WIFI_SSID`/`WIFI_PASS` in `device/config.py`
   (2.4 GHz hotspot), re-copy it to the board, reset.
3. **Run the bridge unprivileged** — `pip install paho-mqtt`, deploy `bridge/`,
   register `run_action` in Songbird's tool harness. Run it as a non-root user
   (see `bridge/songbird-bridge.service`), ideally on the **isolated Kali box**
   so approved commands execute there, not next to the model on lab3. The Kali
   box reaches the broker over the Funnel, so its config uses
   `homelab.tail35b6c6.ts.net:10000`.

### 2. Fill in config
The shared `SECRET_HEX` is already generated and identical in both files — don't
change it. Fill the rest:
- `device/config.py` — `WIFI_SSID/PASS` (your hotspot, 2.4 GHz: iPhone →
  "Maximize Compatibility"), and `MQTT_BROKER/PORT/USER/PASS`.
- `bridge/config.py` — the same `MQTT_*` values.

Re-copy the device config after editing:
```bash
cd songbird-token/device
mpremote connect /dev/cu.usbmodem1101 fs cp config.py :config.py
mpremote connect /dev/cu.usbmodem1101 reset
```
On boot the OLED shows the logo + the board's IP once it's on Wi-Fi and the
broker.

### 3. Run the bridge (unprivileged, off the model host)
```bash
pip install paho-mqtt
python3 bridge/bridge.py "echo hello from songbird"
```
The token screen shows the exact command; after the brief read delay, press
BOOT to run it, or wait it out and it's denied. For LAN testing before the
Funnel is up: `MQTT_BROKER_OVERRIDE=192.168.1.253 MQTT_PORT_OVERRIDE=8883`.

### 4. Wire it to Songbird
`bridge.py` exposes `TOOL_SPEC` (an OpenAI-style function spec) and
`handle_tool_call(name, args)`. Register `run_action` as a tool in whatever
harness drives Songbird; when the model calls it, the approval flow runs
automatically.

## Security model
- **You sign the exact command you see.** The request carries the real command;
  the OLED shows it (scrolling if long) and the press signs
  `HMAC-SHA256(secret, id|nonce|command)`. The bridge recomputes that over the
  command it is about to run and rejects any mismatch — so the model cannot show
  one command and run another. (Tested: valid press runs; forged secret and
  signed-a-different-command are both rejected.)
- **Nothing runs without a press** — except exact strings in `ALLOWLIST`
  (empty by default). No wildcards, no "all read-only" blanket.
- **Single-use nonce** per request, so an approval can't be replayed.
- **Minimum view time** (`MIN_VIEW_MS`, 2.5s): the button is ignored until the
  command has been on screen long enough to actually read — no blind-approving.
- **TLS is verified** against the broker's cert (`certs/broker.crt`) on both the
  device and the bridge, so a MITM can't impersonate the broker. The device
  connects by the cert's DNS name; the bridge verifies the chain even over the
  LAN IP.
- **Run the bridge unprivileged and off the model host.** Approved commands run
  with the bridge's privileges — use the hardened `songbird-bridge.service` as a
  non-root user, on the isolated Kali box.
- **Secrets stay out of git.** `bridge/config.py` and `device/config.py` hold
  the live secret + broker passwords and are `.gitignore`d; commit only the
  `config.example.py` templates. If a secret ever leaks, regenerate it in both
  configs and re-copy to the board.

### Residual risk you still own
- **Approval fatigue** — the gate is only as careful as you are at each press.
- **Physical possession** — whoever holds the board can approve; treat it as a key.
- **Public exposure** — once the Funnel is up, the broker has an internet
  endpoint. Auth + the signing secret are what stand in front of it.

## Swapping in a real logo
Convert a ≤128×64 1-bit PNG at https://javl.github.io/image2cpp/ (Arduino
single-bitmap, horizontal), then replace `draw_logo()` in `device/logo.py` with
a `framebuf.FrameBuffer` blit of the byte array. Re-copy `logo.py` and reset.
```
