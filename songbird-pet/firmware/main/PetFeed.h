#pragma once
// ============================================================
// PetFeed - what the Mac is up to, from songbird-pet/host/pet_feed.py
// ============================================================
// The Mac publishes a small retained JSON message to PET_FEED_TOPIC on the
// Songbird broker; we subscribe over TLS (the broker's own cert is embedded
// and checked). Button events go back on PET_EVENT_TOPIC.
//
// esp-mqtt runs in its own task and reconnects by itself, so the main loop
// only ever copies out the latest state.
#include <Arduino.h>
#include "mqtt_client.h"
#include "cJSON.h"
#include "mbedtls/base64.h"
#include "lwip/dns.h"
#include "lwip/ip_addr.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "songbird_config.h"

extern const char broker_crt_start[] asm("_binary_broker_crt_start");

#define FEED_STALE_MS 120000UL   // no word from the Mac for this long -> offline
#define FEED_ART_MAX 1024        // bytes: up to 640x12 px of song line (1 bit per px)
#define FEED_MSG_MAX 4096        // biggest message we take; the art makes them ~1.5 KB

struct FeedState {
    char mode[12] = "offline";   // music code game call browse chat make write away idle offline
    char track[64] = "";
    char artist[48] = "";
    bool playing = false;
    float pos = 0, dur = 0;      // seconds into / length of the track
    long active = 0;             // seconds at the Mac without a break
    int batt = -1;               // Mac battery %, -1 = unknown
    bool charging = false;
    unsigned long at = 0;        // millis() when it arrived, 0 = never
    // The song line drawn by the Mac in a real font (Japanese and all):
    // packed 1-bit rows, MSB first, as drawBitmap takes them. artW 0 = none.
    uint8_t art[FEED_ART_MAX];
    int artW = 0, artH = 0;
};

class PetFeed {
public:
    void start() {
        if (client) return;
        lock = xSemaphoreCreateMutex();

#ifdef PET_DNS
        // Ask a public resolver for the broker's name: phone hotspots hand
        // back a private address for the Tailscale Funnel host.
        ip_addr_t dns;
        if (ipaddr_aton(PET_DNS, &dns)) dns_setserver(0, &dns);
#endif

        esp_mqtt_client_config_t cfg = {};
        cfg.broker.address.uri = PET_MQTT_URI;
        cfg.broker.verification.certificate = broker_crt_start;
        cfg.credentials.username = PET_MQTT_USER;
        cfg.credentials.authentication.password = PET_MQTT_PASS;
        cfg.credentials.client_id = "songbird-pet-s3";
        cfg.session.keepalive = 60;
        cfg.network.reconnect_timeout_ms = 10000;
        cfg.buffer.size = FEED_MSG_MAX;          // messages carry the song-line picture
        client = esp_mqtt_client_init(&cfg);
        esp_mqtt_client_register_event(client, MQTT_EVENT_ANY, onEvent, this);
        esp_mqtt_client_start(client);
        Serial.printf("[feed] connecting to %s\n", PET_MQTT_URI);
    }

    bool started() const { return client != nullptr; }
    bool isConnected() const { return connected; }

    // Latest state; `fresh` false if the Mac has gone quiet.
    FeedState get() {
        FeedState s;
        if (!lock) return s;
        xSemaphoreTake(lock, portMAX_DELAY);
        s = latest;
        xSemaphoreGive(lock);
        if (s.at == 0 || millis() - s.at > FEED_STALE_MS) strcpy(s.mode, "offline");
        return s;
    }

    void send(const char *json) {
        if (client && connected)
            esp_mqtt_client_publish(client, PET_EVENT_TOPIC, json, 0, 0, 0);
    }

private:
    esp_mqtt_client_handle_t client = nullptr;
    SemaphoreHandle_t lock = nullptr;
    FeedState latest;
    volatile bool connected = false;

    static void copyStr(char *dst, size_t n, cJSON *item) {
        if (cJSON_IsString(item)) {
            strncpy(dst, item->valuestring, n - 1);
            dst[n - 1] = 0;
        } else {
            dst[0] = 0;
        }
    }

    void parse(const char *data, int len) {
        static char buf[FEED_MSG_MAX + 1];       // MQTT task only; too big for its stack
        if (len <= 0 || len >= (int)sizeof(buf)) return;
        memcpy(buf, data, len);
        buf[len] = 0;
        cJSON *j = cJSON_Parse(buf);
        if (!j) return;
        static FeedState s;                      // ~1 KB: keep it off the MQTT task's stack
        s = FeedState();
        copyStr(s.mode, sizeof(s.mode), cJSON_GetObjectItem(j, "mode"));
        if (!s.mode[0]) strcpy(s.mode, "idle");
        copyStr(s.track, sizeof(s.track), cJSON_GetObjectItem(j, "track"));
        copyStr(s.artist, sizeof(s.artist), cJSON_GetObjectItem(j, "artist"));
        s.playing = cJSON_IsTrue(cJSON_GetObjectItem(j, "playing"));
        cJSON *n;
        if (cJSON_IsNumber(n = cJSON_GetObjectItem(j, "pos"))) s.pos = n->valuedouble;
        if (cJSON_IsNumber(n = cJSON_GetObjectItem(j, "dur"))) s.dur = n->valuedouble;
        if (cJSON_IsNumber(n = cJSON_GetObjectItem(j, "active"))) s.active = n->valueint;
        if (cJSON_IsNumber(n = cJSON_GetObjectItem(j, "batt"))) s.batt = n->valueint;
        s.charging = cJSON_IsTrue(cJSON_GetObjectItem(j, "charging"));
        cJSON *art = cJSON_GetObjectItem(j, "art");
        if (cJSON_IsObject(art)) {
            cJSON *aw = cJSON_GetObjectItem(art, "w"), *ah = cJSON_GetObjectItem(art, "h");
            cJSON *ab = cJSON_GetObjectItem(art, "b");
            size_t got = 0;
            if (cJSON_IsNumber(aw) && cJSON_IsNumber(ah) && cJSON_IsString(ab) &&
                mbedtls_base64_decode(s.art, sizeof(s.art), &got, (const unsigned char *)ab->valuestring,
                                      strlen(ab->valuestring)) == 0 &&
                got == (size_t)((aw->valueint + 7) / 8 * ah->valueint)) {
                s.artW = aw->valueint;
                s.artH = ah->valueint;
                if (s.artW != latest.artW) Serial.printf("[feed] song line %dx%d px\n", s.artW, s.artH);
            }
        }
        s.at = millis();
        if (s.at == 0) s.at = 1;
        cJSON_Delete(j);

        xSemaphoreTake(lock, portMAX_DELAY);
        latest = s;
        xSemaphoreGive(lock);
    }

    static void onEvent(void *arg, esp_event_base_t, int32_t id, void *data) {
        PetFeed *self = (PetFeed *)arg;
        esp_mqtt_event_handle_t ev = (esp_mqtt_event_handle_t)data;
        switch ((esp_mqtt_event_id_t)id) {
            case MQTT_EVENT_CONNECTED:
                self->connected = true;
                esp_mqtt_client_subscribe(self->client, PET_FEED_TOPIC, 1);
                Serial.println("[feed] connected, subscribed");
                break;
            case MQTT_EVENT_DISCONNECTED:
                self->connected = false;
                Serial.println("[feed] disconnected");
                break;
            case MQTT_EVENT_DATA:
                // small messages arrive whole; ignore anything chunked
                if (ev->current_data_offset == 0 && ev->data_len == ev->total_data_len)
                    self->parse(ev->data, ev->data_len);
                break;
            default:
                break;
        }
    }
};
