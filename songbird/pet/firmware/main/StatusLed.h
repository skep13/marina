#pragma once
// ============================================================
// StatusLed - the board's RGB LED (a WS2812) held at one colour
// ============================================================
// Songbird: a steady soft blue as the "on" light. The red power LED next to
// it is wired to 3.3V on these boards, so firmware can't switch that one off.
#include "led_strip.h"
#include "songbird_config.h"

class StatusLed {
public:
    void begin() {
#if PET_LED_GPIO >= 0
        led_strip_config_t strip = {};
        strip.strip_gpio_num = PET_LED_GPIO;
        strip.max_leds = 1;
        strip.led_pixel_format = LED_PIXEL_FORMAT_GRB;
        strip.led_model = LED_MODEL_WS2812;
        led_strip_rmt_config_t rmt = {};
        rmt.clk_src = RMT_CLK_SRC_DEFAULT;
        rmt.resolution_hz = 10 * 1000 * 1000;
        if (led_strip_new_rmt_device(&strip, &rmt, &handle) != ESP_OK) {
            handle = nullptr;
            return;
        }
        set(PET_LED_R, PET_LED_G, PET_LED_B);
#endif
    }

    void set(uint8_t r, uint8_t g, uint8_t b) {
        if (!handle) return;
        led_strip_set_pixel(handle, 0, r, g, b);
        led_strip_refresh(handle);
    }

private:
    led_strip_handle_t handle = nullptr;
};
