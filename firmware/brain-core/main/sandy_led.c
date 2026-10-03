// On-board WS2812 (see sandy_led.h). One task owns the pixel; callers post and return.

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
#if ENABLE_VOICE
#include "sandy_voice.h"
#endif

static const char *TAG = "led";

static led_strip_handle_t s_strip;

// Written by callers, read by the task. Single-word scalars, no lock needed.
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

// Integer maths: runs 50×/s and the FPU belongs to audio.
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

// Kept dim: it sits right in front of the face.
static void paint_state(sandy_led_state_t st) {
    switch (st) {
    case LED_STATE_IDLE:       put(0, 0, 12);   break;
    case LED_STATE_LISTENING:  put(40, 40, 40); break;
    case LED_STATE_TALKING:    put(40, 18, 0);  break;
    case LED_STATE_OFF:
    default:                   put(0, 0, 0);    break;
    }
}

// Ask the mic, not the last colour: a network-error banner turned the light off mid-session.
static bool session_live(void) {
#if ENABLE_VOICE
    return voice_session_is_active();
#else
    return false;
#endif
}

static void led_task(void *arg) {
    (void)arg;
    int frame = 0;
    int last_fx = -1;   // restart the effect when it changes
    // -1 forces a repaint of the indicator.
    int last = -1;

    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(FRAME_MS));

        if (s_state_owns || session_live()) {
            // Privacy indicator holds the light; repaint only on change. During a session it can only say "live".
            sandy_led_state_t st = s_state;
            if (session_live() && st != LED_STATE_TALKING) st = LED_STATE_LISTENING;
            if (st == LED_STATE_IDLE) {
                // Idle breathes slowly, so it reads as alive rather than stuck.
                static int idle_lvl = -1;
                int t = (int)((xTaskGetTickCount() * portTICK_PERIOD_MS) % 6000);
                int tri = t < 3000 ? t : 6000 - t;          // 0..3000..0
                int lvl = 4 + tri * 10 / 3000;               // 4..14
                if (last != (int)st || lvl != idle_lvl) {
                    put(0, 0, (uint8_t)lvl);
                    idle_lvl = lvl;
                    last = (int)st;
                }
            } else if (last != (int)st) {
                paint_state(st);
                last = (int)st;
            }
            frame = 0;
            last_fx = -1;
            continue;
        }
        // Forget the last state, or the effect's last colour stays lit.
        last = -1;

        const int  spd = s_speed < 1 ? 1 : (s_speed > 10 ? 10 : s_speed);
        const uint32_t rgb = s_rgb;
        const uint8_t  cr = (rgb >> 16) & 0xFF, cg = (rgb >> 8) & 0xFF, cb = rgb & 0xFF;
        uint8_t r = 0, g = 0, b = 0;
        // Restart the frame count per effect, or a sunrise after a rainbow starts "finished".
        if ((int)s_fx != last_fx) { last_fx = (int)s_fx; frame = 0; }
        frame++;

        switch (s_fx) {
        case LED_FX_RAINBOW:
            hue_to_rgb(frame * spd / 2, 60, &r, &g, &b);
            break;

        case LED_FX_BREATHE: {
            // Triangle wave: no float, indistinguishable at this size.
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
            // Runs once and stops.
            int steps = 600 / spd;
            int t = frame > steps ? steps : frame;
            r = 20 + t * 235 / steps;
            g = t * 140 / steps;
            // Integer order matters: t*t/steps/steps is 0 until the last frame.
            b = (uint8_t)((int32_t)t * t * 60 / ((int32_t)steps * steps));
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
    // Priority 1: a dropped animation frame is invisible, an audio frame is not.
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

    // Refuse while audio can leave the room: the privacy light must stay visible.
    if (session_live() || s_state == LED_STATE_LISTENING || s_state == LED_STATE_TALKING) {
        ESP_LOGW(TAG, "effect refused — the light is showing a live session");
        return false;
    }

    // No colour keeps the current one.
    if (rgb != LED_RGB_KEEP) s_rgb = rgb & 0xFFFFFF;
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

#else  // !ENABLE_LED

#include "sandy_led.h"

// No LED: the status and broker commands that drive it do nothing.
void led_set_state(sandy_led_state_t state) { (void)state; }
bool led_set_effect(sandy_led_fx_t fx, uint32_t rgb, int speed) {
    (void)fx; (void)rgb; (void)speed;
    return false;
}
sandy_led_fx_t led_fx_from_name(const char *name) { (void)name; return LED_FX_COUNT; }

#endif // ENABLE_LED
