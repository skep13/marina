#pragma once
// ====================================================================
//  Songbird pet - local settings. Copy to songbird_config.h and fill in.
//  songbird_config.h is gitignored: it holds the broker password.
// ====================================================================

// Time zone as a POSIX TZ string (handles summer time on its own).
#define PET_TZ "GMT0BST,M3.5.0/1,M10.5.0"   // UK

// Wi-Fi, in order of preference (e.g. phone hotspot first). A network saved
// on the setup page (triple-press BOOT, join "PetRobot-Setup", open
// 192.168.4.1) is tried after these. Leave empty to rely on that page.
#define PET_WIFI_SSID ""
#define PET_WIFI_PASS ""
// Second choice (e.g. home), tried when the first isn't around.
#define PET_WIFI2_SSID ""
#define PET_WIFI2_PASS ""
// Third choice (e.g. college).
#define PET_WIFI3_SSID ""
#define PET_WIFI3_PASS ""

// RGB status LED (WS2812): GPIO48 on most S3 devkits, GPIO38 on some
// revisions; -1 to leave it off. Colour 0-255 per channel, kept dim.
#define PET_LED_GPIO 48
#define PET_LED_R 0
#define PET_LED_G 0
#define PET_LED_B 24

// Screen orientation: 0 normal, 2 = turned 180 degrees (text follows the
// yellow strip either way)
#define PET_SCREEN_ROTATION 0

// Feed from the Mac (songbird-pet/host/pet_feed.py) through the Songbird
// broker. Set PET_FEED_ENABLED to 0 to run as a plain offline desk pet.
#define PET_FEED_ENABLED 1
#define PET_MQTT_URI   "mqtts://homelab.tail35b6c6.ts.net:10000"
#define PET_MQTT_USER  "token-device"
#define PET_MQTT_PASS  "change-me"
#define PET_FEED_TOPIC  "songbird/pet"
#define PET_EVENT_TOPIC "songbird/pet/event"
// Hotspot DNS gives a wrong answer for the Funnel name; ask a public resolver.
#define PET_DNS "8.8.8.8"

// Focus timer
#define PET_FOCUS_MIN 25
#define PET_BREAK_MIN 5
#define PET_LONG_BREAK_MIN 15     // every 4th break

// Nudge to get up after this long at the Mac without a break
#define PET_STRETCH_AFTER_MIN 90

// Hours she treats as night: falls asleep when you're away, screen dims
#define PET_NIGHT_FROM 23
#define PET_NIGHT_TO 7
