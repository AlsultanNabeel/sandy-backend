// On-board WS2812 (GPIO 48). Contract and reasoning: include/sandy_led.h
//
// One task owns the pixel. Everything else posts a request and returns, so a
// caller asking for a two-minute rainbow does not block for two minutes, and
// the voice link can take the light back instantly when a session opens.

#include "config.h"
#if ENABLE_LED

#include "sandy_led.h"
#include <stdlib.h>
#include <string.h>
#include "esp_log.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "led_strip.h"

static const char *TAG = "led";

static led_strip_handle_t s_strip;

// What the light should be doing. Written by callers, read by the effect task.
// Plain scalars, each written in one instruction — no lock needed, and a torn
// read at worst shows one wrong frame twenty milliseconds long.
static volatile sandy_led_fx_t     s_fx    = LED_FX_OFF;
static volatile uint32_t           s_rgb   = 0x00A0FF;
static volatile int                s_speed = 5;
static volatile sandy_led_state_t  s_state = LED_STATE_IDLE;
static volatile bool               s_state_owns;   // indicator, not effect

#define FRAME_MS 20

static void put(uint8_t r, uint8_t g, uint8_t b) {
    if (!s_strip) return;
    led_strip_set_pixel(s_strip, 0, r, g, b);
    led_strip_refresh(s_strip);
}

// Hue (0..359) to RGB at full saturation, scaled by `v` (0..255).
// Integer maths on purpose: this runs fifty times a second forever, and the
// float unit is wanted by the audio path.
static void hue_to_rgb(int hue, int v, uint8_t *r, uint8_t *g, uint8_t *b) {
    hue = ((hue % 360) + 360) % 360;
    int region = hue / 60;
    int rem    = (hue % 60) * 255 / 60;
    int p = 0, q = v * (255 - rem) / 255, t = v * rem / 255;
    switch (region) {
    case 0: *r = v; *g = t; *b = p; break;
    case 1: *r = q; *g = v; *b = p; break;
    case 2: *r = p; *g = v; *b = t; break;
    case 3: *r = p; *g = q; *b = v; break;
    case 4: *r = t; *g = p; *b = v; break;
    default:*r = v; *g = p; *b = q; break;
    }
}

// The indicator colours. Kept dim: this sits on a desk in front of a face, and
// a full-brightness WS2812 at arm's length is unpleasant to sit beside.
static void paint_state(sandy_led_state_t st) {
    switch (st) {
    case LED_STATE_IDLE:       put(0, 0, 12);   break;
    case LED_STATE_LISTENING:  put(40, 40, 40); break;
    case LED_STATE_TALKING:    put(40, 18, 0);  break;
    case LED_STATE_OFF:
    default:                   put(0, 0, 0);    break;
    }
}

static void led_task(void *arg) {
    (void)arg;
    int frame = 0;

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(FRAME_MS));

        if (s_state_owns) {
            // The privacy indicator holds the light. Repaint only on change —
            // refreshing an unchanged pixel fifty times a second is pure noise
            // on the RMT peripheral.
            // -1 is not a valid state, so the first pass always paints.
            static int last = -1;
            if (last != (int)s_state) { paint_state(s_state); last = (int)s_state; }
            frame = 0;
            continue;
        }

        const int  spd = s_speed < 1 ? 1 : (s_speed > 10 ? 10 : s_speed);
        const uint32_t rgb = s_rgb;
        const uint8_t  cr = (rgb >> 16) & 0xFF, cg = (rgb >> 8) & 0xFF, cb = rgb & 0xFF;
        uint8_t r = 0, g = 0, b = 0;
        frame++;

        switch (s_fx) {
        case LED_FX_RAINBOW:
            hue_to_rgb(frame * spd / 2, 60, &r, &g, &b);
            break;

        case LED_FX_BREATHE: {
            // Triangle wave rather than a sine: no float, and at this size the
            // eye cannot tell them apart.
            int period = 400 / spd, t = frame % period;
            int lvl = t < period / 2 ? (t * 255 / (period / 2))
                                     : (255 - (t - period / 2) * 255 / (period / 2));
            r = cr * lvl / 255; g = cg * lvl / 255; b = cb * lvl / 255;
            break;
        }

        case LED_FX_PULSE: {
            int period = 100 / spd + 10, t = frame % period;
            int lvl = 255 - (t * 255 / period);        // snap on, decay off
            r = cr * lvl / 255; g = cg * lvl / 255; b = cb * lvl / 255;
            break;
        }

        case LED_FX_BLINK: {
            int half = 40 / spd + 2;
            bool on = ((frame / half) % 2) == 0;
            r = on ? cr : 0; g = on ? cg : 0; b = on ? cb : 0;
            break;
        }

        case LED_FX_FIRE: {
            int flick = (int)(esp_random() % 60);
            r = 70 + flick; g = 12 + flick / 4; b = 0;
            break;
        }

        case LED_FX_POLICE: {
            int half = 30 / spd + 2;
            bool red = ((frame / half) % 2) == 0;
            r = red ? 90 : 0; g = 0; b = red ? 0 : 90;
            break;
        }

        case LED_FX_PARTY: {
            int hold = 20 / spd + 1;
            if (frame % hold == 0) {
                hue_to_rgb((int)(esp_random() % 360), 80, &r, &g, &b);
            } else {
                continue;    // hold the previous colour; do not repaint
            }
            break;
        }

        case LED_FX_SUNRISE: {
            // Runs once and stops, which is the point of a sunrise.
            int steps = 600 / spd;
            int t = frame > steps ? steps : frame;
            r = 20 + t * 235 / steps;
            g = t * 140 / steps;
            b = t * t / steps / steps * 60;
            if (frame >= steps) { s_fx = LED_FX_SOLID; s_rgb = 0xFF8C3C; }
            break;
        }

        case LED_FX_OCEAN:
            hue_to_rgb(150 + (frame * spd / 6) % 90, 45, &r, &g, &b);
            break;

        case LED_FX_CANDLE: {
            int flick = (int)(esp_random() % 18);
            r = 30 + flick; g = 8 + flick / 3; b = 0;
            break;
        }

        case LED_FX_SOLID:
            r = cr; g = cg; b = cb;
            break;

        case LED_FX_OFF:
        default:
            r = g = b = 0;
            break;
        }

        put(r, g, b);
    }
}

esp_err_t led_init(void) {
    led_strip_config_t strip_cfg = {
        .strip_gpio_num = PIN_W2812,
        .max_leds = 1,
    };
    led_strip_rmt_config_t rmt_cfg = {
        .resolution_hz = 10 * 1000 * 1000,
    };
    esp_err_t err = led_strip_new_rmt_device(&strip_cfg, &rmt_cfg, &s_strip);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "init failed: %s", esp_err_to_name(err));
        return err;
    }
    s_state_owns = true;
    s_state = LED_STATE_IDLE;
    paint_state(LED_STATE_IDLE);
    // 2048: integer maths and one driver call per frame. Priority 1 — a dropped
    // animation frame is invisible; a dropped audio frame is not.
    xTaskCreate(led_task, "led_fx", 2048, NULL, 1, NULL);
    ESP_LOGI(TAG, "ready on GPIO %d", PIN_W2812);
    return err;
}

void led_set_state(sandy_led_state_t state) {
    s_state = state;
    s_state_owns = true;      // the indicator takes the light back
}

bool led_set_effect(sandy_led_fx_t fx, uint32_t rgb, int speed) {
    if (fx < 0 || fx >= LED_FX_COUNT) return false;

    // While a session is open the light means "audio is leaving this room" and
    // nothing may paint over it. Refusing is the honest answer; accepting and
    // showing nothing would be worse than either.
    if (s_state == LED_STATE_LISTENING || s_state == LED_STATE_TALKING) {
        ESP_LOGW(TAG, "effect refused — the light is showing a live session");
        return false;
    }

    s_rgb   = rgb;
    s_speed = speed;
    s_fx    = fx;
    s_state_owns = (fx == LED_FX_OFF);   // "off" hands the light back
    ESP_LOGI(TAG, "effect %d rgb=%06x speed=%d", (int)fx, (unsigned)rgb, speed);
    return true;
}

static const struct { const char *name; sandy_led_fx_t fx; } FX_NAMES[] = {
    {"off", LED_FX_OFF},         {"rainbow", LED_FX_RAINBOW},
    {"breathe", LED_FX_BREATHE}, {"pulse", LED_FX_PULSE},
    {"blink", LED_FX_BLINK},     {"fire", LED_FX_FIRE},
    {"police", LED_FX_POLICE},   {"party", LED_FX_PARTY},
    {"sunrise", LED_FX_SUNRISE}, {"ocean", LED_FX_OCEAN},
    {"candle", LED_FX_CANDLE},   {"solid", LED_FX_SOLID},
};

sandy_led_fx_t led_fx_from_name(const char *name) {
    if (!name) return LED_FX_COUNT;
    for (size_t i = 0; i < sizeof(FX_NAMES) / sizeof(FX_NAMES[0]); i++) {
        if (strcmp(FX_NAMES[i].name, name) == 0) return FX_NAMES[i].fx;
    }
    return LED_FX_COUNT;
}

#endif // ENABLE_LED
