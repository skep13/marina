# Airspace Watchdog — plan

Give Marina a sense she doesn't have today: the wireless world around your
Mac. A small ESP32-S3 on your desk listens to the Wi-Fi and Bluetooth air,
reports what it hears to Marina's server, and she watches that stream the way
she already watches what you're doing on the Mac — quiet most of the time,
speaking up only when something is genuinely worth a word.

This is the defensive mirror of the "radio recon" we talked through. The board
only ever *listens*. It never transmits an attack, never touches a network,
never joins anything. Everything it does is receive-only, and everything it
watches is your own airspace.

## What it feels like to use

Most of the day: nothing. It sits there.

- You sit down in the morning: *"Morning. Same twelve devices around you as
  last night, nothing new."* (Only if you've asked her to greet you — otherwise
  silence.)
- A phone you don't know parks near your flat for an hour: *"There's a device
  that's been sitting near you for about an hour that I haven't seen before.
  Probably nothing, just flagging it."*
- You're in a café and a hotspot shows up calling itself your home network's
  name: *"Careful — something here is broadcasting as 'YourHomeWiFi' but it
  isn't your router. Looks like an evil twin. Don't auto-join it."*
- Someone runs a deauth burst near you: *"I'm seeing deauth frames in the air —
  that's the thing that kicks devices off Wi-Fi. Someone nearby is doing it."*

And you can ask her, any time:

- "What's around me right now?" → she reads the current picture.
- "Is this network safe to join?" → she checks it against what she's seen.
- "Has anything new shown up today?" → she lists it.

She's the analyst and the voice. The board is just the ears.

## How it fits Marina's existing shape

Nothing here is a new kind of thing for her — it maps onto parts that already
exist:

| Need | Existing pattern it copies |
| --- | --- |
| A networked capability, config-gated, easy to revoke | `process/tools/workspace.py` (her Linux box over SSH) |
| Watch a stream, decide what's worth saying | `process/notice.py` (the `Watcher` for "you've been away / in one app too long") |
| Speak up on her own, respecting mute / quiet hours / rate limit | `_announce()` → `pending_announcement()` in `tools/registry.py`, out the same long poll as her other openers |
| Tools she can call when *you* ask | the `SPECS` list pattern every tool module uses |
| On/off per preset (e.g. off during a demo) | `setting("tools", key, ...)` gating |

So it's one new firmware image on the board and one new server module that
behaves like the ones already there.

## Pieces

### 1. Board firmware (receive-only)

Flashed to the ESP32-S3. On your Wi-Fi, powered by USB or a phone charger.

- **Wi-Fi monitor mode** — passively reads beacon and management frames in the
  air: which access points are broadcasting, their SSID/BSSID/channel/signal,
  and management frames like deauths. This is listening, not joining.
- **BLE scan** — passively lists Bluetooth devices advertising nearby and their
  signal strength (presence, not contents).
- **Reports out** — every few seconds it POSTs a small JSON summary to Marina's
  server over your LAN (e.g. `{aps: [...], ble: [...], deauths: n}`), with a
  shared token so only your board is believed.
- Deliberately *not* included: no deauth, no sending, no joining networks, no
  packet capture of other people's traffic. If it can't be done by listening,
  it isn't in the firmware.

Screen is optional and comes later — when it's soldered on it shows the current
count and a colour (calm / something new / warning). The watchdog works fully
without it.

### 2. Server module — `process/airspace.py` + `process/tools/airspace.py`

- **Ingest**: a tiny endpoint on the existing FastAPI server (e.g.
  `POST /airspace/report`) that the board posts to, token-checked, keeping only
  the latest picture in memory. Nothing written to disk by default.
- **Baseline**: first day or two it just learns — what's normally around you
  becomes "known". After that, *new* is what's interesting.
- **Analyzer**: a `Watcher`-style object (modelled on `notice.py`) fed each
  report, holding state and deciding when something crosses a line worth
  mentioning. It produces plain findings, not raw data.
- **Speak**: findings go through `_announce()`, so they ride the existing
  proactive pipeline — mute, quiet hours and `max_per_hour` all apply for free.
  She phrases them herself in her own voice; the module hands her the fact, not
  the wording.
- **Ask tools** (`SPECS`): read-only functions the model can call when you ask —
  `airspace_now()`, `airspace_check(ssid)`, `airspace_new_today()`. Gated by
  `setting("tools", "airspace", ...)` like every other tool.

### 3. Config — in `character_config.yaml`

```yaml
airspace:
  enabled: false          # off until you turn it on
  token: "..."            # shared secret the board signs its reports with
  learn_hours: 24         # how long to treat everything as "known" at first
  quiet: true             # only speak for real warnings, not every new phone
tools:
  airspace: true          # let her answer questions about it
```

Revoking it is setting `enabled: false`. One line.

## What it can actually detect (and the honest limits)

**Can detect, passively:**
- A new / unknown device lingering near you.
- An evil twin — your SSID broadcast by a BSSID that isn't your router.
- A rogue open AP impersonating a network you trust.
- Deauth / disassoc frames in the air (someone running that attack nearby).
- Beacon floods (a room spammed with fake networks).

**Can't, and I won't pretend otherwise:**
- It can't read anyone's traffic — modern Wi-Fi is encrypted, and we're not
  trying to.
- It can't tell you *who* a device belongs to, only that it's there.
- Range is roughly a room / a floor, not a building.
- It will have false alarms early on; that's what the learning period and the
  rate limit are for.

This is a situational-awareness sensor, not an x-ray.

## Build order

1. **Firmware v0** — board scans and prints to USB serial. Prove it hears the
   air, nothing networked yet. *(On your own airspace; verifiable on the Mac.)*
2. **Report path** — board POSTs to a stub endpoint; confirm Marina's server
   receives clean JSON over your LAN.
3. **Analyzer + baseline** — learn "known", detect "new". Still silent, just
   logs findings so we can tune thresholds against your real surroundings.
4. **Give her the voice** — wire findings into `_announce()`; she starts
   speaking up. Tune quiet hours / rate so it's calm.
5. **Ask tools** — `airspace_now` etc. so you can query her.
6. **Screen (after soldering)** — mirror the state on the display.

Each step is testable on its own, on your own network, before the next.

## The line this stays inside

Receive-only firmware, your own airspace, your own Mac. No transmitting, no
joining, no reading anyone's traffic, no targeting anything that isn't yours.
If a feature can't be done by listening to your own surroundings, it's not part
of this.
