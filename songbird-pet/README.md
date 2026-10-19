# Songbird pet

The ESP32-S3 in the keyring case, turned into a desk pet. It's built on
[ZnFr60/ESP32C3-Desk-pet](https://github.com/ZnFr60/ESP32C3-Desk-pet) (the
RoboEyes face, 23 expressions, 19 activities, mood system), ported to the S3
and taught to follow what the Mac is doing:

| On the Mac | The pet |
|---|---|
| Spotify / Music open | the record replaces her eyes: spinning while a song plays, track scrolling with a progress bar |
| ...paused or nothing loaded | record stops, tonearm parks |
| VS Code, Terminal, Xcode, Claude... | a terminal typing code |
| Steam, Minecraft, Roblox | a little space shooter |
| Zoom, FaceTime, Teams | an oscilloscope trace of a voice |
| Safari, Chrome, Firefox, Arc | a radar sweep |
| Discord, Slack, Messages, Mail | two speech bubbles taking turns |
| Bambu / Orca / Prusa / Cura, Fusion, Blender, Figma | a 3D printer building a vase |
| Pages, Word, Notes, Obsidian | a page filling up |
| nobody at the keyboard 5 min | looks around for you; asleep at night |
| 90 min at the Mac without a break | "Stretch break?" every 15 min |
| Mac battery under 20% | sad, "Mac batt low" |

These scenes replace her eyes, drawn clean; a single press still gets a
reaction from her. Between activities she does her own thing (looks
around, yawns, gets bored) with her eyes in a little CRT tube. The yellow
strip is a readout: a twinkling starburst, the label, and a leaning
seven-segment clock or focus timer.

Song titles in any script (Japanese included) are drawn on the Mac in
Hiragino and sent as a 1-bit picture, since the pet's own font is ASCII.

```
Mac: host/pet_feed.py ──► broker (ct102, TLS) ──► S3 firmware
                 ▲                                    │
                 └──── button events (play/pause, ◄───┘
                       focus timer done)
```

## Button (BOOT)

| Press | Does |
|---|---|
| single | pet her |
| double | music on: play/pause the Mac · timer paused: reset it · otherwise: a random trick |
| hold ~1 s | focus timer: start / pause / resume (25 min focus, 5 min break, 15 every 4th) |
| triple | Wi-Fi setup page (join `PetRobot-Setup`, open `192.168.4.1`) |
| hold 3 s | power off (BOOT wakes her) |

The timer shows top-right (`F 24:13`); when a phase ends the screen flashes
and the Mac shows a notification.

## Firmware (`firmware/`)

ESP-IDF v5.3.1, installed in `~/esp/esp-idf`.

```bash
cp firmware/main/songbird_config.example.h firmware/main/songbird_config.h   # then fill it in
cd firmware && . ~/esp/esp-idf/export.sh && idf.py build
idf.py -p /dev/cu.usbmodem1101 flash
```

- S3 pins: OLED SDA=GPIO8, SCL=GPIO9 (0x3C), button GPIO0. No MPU6050 on
  this board, so the motion reactions are idle until one is wired to the
  same I2C bus.
- Wi-Fi stays on (upstream turns it off after the time sync to save power,
  but the feed needs it; the S3 runs off USB anyway). It tries the networks
  in the config in order (`PET_WIFI_SSID`, `PET_WIFI2_SSID`, `PET_WIFI3_SSID`:
  hotspot, home, college), then any saved on the setup page, and retries every
  minute.
- The broker certificate (`main/broker.crt`) is embedded and checked.
- The RGB LED is held a dim blue as the "on" light (`PET_LED_*` in the
  config; GPIO48, or 38 on some boards). The red power LED is hardwired to
  3.3 V, so it can only be covered, not switched off.
- `idf.py flash` resets the board into download mode on its own. Only the
  very first flash over MicroPython needed BOOT held while tapping RST.

Changes from upstream, all marked "Songbird" in the code: `Config.h` pins,
`sdkconfig.defaults` target, `PetFeed.h`, `FocusTimer.h`, the Music state
and feed hooks in `RoboEyesManager.h`, `songbirdTick()` and the button
changes in `esp32-pet-robot-arduino.cpp`, the time zone in `TimeManager.h`, and a fix in `compat/WString.h`: String
assignment leaked its old buffer every time (upstream lost memory once a
second through the clock text; with the feed it ran out within seconds).

Upstream has no licence file, so keep this fork private.

## Mac side (`host/`)

```bash
pip install paho-mqtt
cp host/feed_config.example.json host/feed_config.json   # fill in the broker password
python3 host/pet_feed.py --once     # print what it sees
python3 host/pet_feed.py            # run it by hand
```

To start it at login and keep it running:

```bash
cp host/com.songbird.pet-feed.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.songbird.pet-feed.plist
```

Log: `~/Library/Logs/songbird-pet-feed.log`. Restart after editing:
`launchctl kickstart -k gui/$(id -u)/com.songbird.pet-feed`.

The song line is rendered here with Pillow in Hiragino Kaku Gothic W3
at 12 px and sent as `art` (base64, 1 bit per pixel). Plain-ASCII
`track`/`artist` go too, as a fallback if Pillow or the font is missing.

The first run asks for permission to control Spotify/Music (System Settings
→ Privacy & Security → Automation). Add your own apps under `"apps"` in the
config, e.g. `{"Godot": "code"}`.
