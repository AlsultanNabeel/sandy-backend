#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

// On-board WS2812 (GPIO 48). `led_set_state` is the privacy indicator (white =
// audio leaving the room) and always wins; `led_set_effect` paints on top, and a
// voice session cancels any effect.

typedef enum {
    LED_STATE_OFF = 0,
    LED_STATE_IDLE,        // dim blue  — awake, local wake word only
    LED_STATE_LISTENING,   // white — audio leaves the device
    LED_STATE_TALKING,     // amber     — Sandy is speaking
} sandy_led_state_t;

// Effects run until done, replaced, or a voice session takes the light back.
typedef enum {
    LED_FX_OFF = 0,
    LED_FX_RAINBOW,     // slow hue sweep through the whole wheel
    LED_FX_BREATHE,     // one colour fading in and out
    LED_FX_PULSE,       // sharp on, slow decay — a heartbeat
    LED_FX_BLINK,       // plain alternating on/off
    LED_FX_FIRE,        // flickering warm orange
    LED_FX_POLICE,      // hard red/blue alternation
    LED_FX_PARTY,       // random saturated colours, fast
    LED_FX_SUNRISE,     // deep red climbing to warm white, once
    LED_FX_OCEAN,       // slow drift across blues and greens
    LED_FX_CANDLE,      // warm flicker, quiet enough to sleep next to
    LED_FX_SOLID,       // hold one colour
    LED_FX_COUNT
} sandy_led_fx_t;

esp_err_t led_init(void);

// Pass as `rgb` to keep the colour already set.
#define LED_RGB_KEEP 0xFFFFFFFFu

// Always wins: cancels any running effect.
void      led_set_state(sandy_led_state_t state);

// `rgb` is 0xRRGGBB (breathe, pulse, blink, solid); `speed` 1..10, 5 = natural.
// Refused (false) while a voice session is open, to keep the privacy indicator honest.
bool      led_set_effect(sandy_led_fx_t fx, uint32_t rgb, int speed);

// LED_FX_COUNT when unknown.
sandy_led_fx_t led_fx_from_name(const char *name);
