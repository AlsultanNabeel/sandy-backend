#pragma once
#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

// The on-board WS2812 (GPIO 48). One pixel, RMT-driven.
//
// It has two jobs and they must not be confused.
//
// The first is a privacy indicator, and it is not decoration: white means audio
// is leaving this room. Anyone standing in front of her is entitled to know
// that from across the room without opening an app. Nothing may take that
// indication away.
//
// The second is that it is a full-colour LED and only three colours were ever
// used, which is a waste of a part that can do sixteen million.
//
// So the two are layered rather than merged. `led_set_state` remains the
// privacy channel and always wins. `led_set_effect` paints on top of it, and a
// live voice session cancels whatever is playing and returns the indicator —
// the light is honest first and pretty second.

typedef enum {
    LED_STATE_OFF = 0,
    LED_STATE_IDLE,        // dim blue  — awake, local wake word only
    LED_STATE_LISTENING,   // white     — session open, audio leaves the device
    LED_STATE_TALKING,     // amber     — Sandy is speaking
} sandy_led_state_t;

// Effects. Anything not "off" runs until it finishes, until another effect
// replaces it, or until a voice session takes the light back.
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
    LED_FX_CANDLE,      // small warm flicker, quiet enough to sleep next to
    LED_FX_SOLID,       // hold one colour
    LED_FX_COUNT
} sandy_led_fx_t;

esp_err_t led_init(void);

// The privacy indicator. Always wins: calling this cancels any running effect.
void      led_set_state(sandy_led_state_t state);

// Play an effect. `rgb` is 0xRRGGBB and is used by the effects that take a
// colour (breathe, pulse, blink, solid); the rest generate their own.
// `speed` is 1..10, 5 being the natural pace of each effect.
//
// Refused while a voice session is open — the indicator is not decoration and
// must not be paintable over while audio is leaving the room. Returns false so
// a caller can say why rather than appearing to work.
bool      led_set_effect(sandy_led_fx_t fx, uint32_t rgb, int speed);

// Look up an effect by the name the app sends. LED_FX_COUNT when unknown.
sandy_led_fx_t led_fx_from_name(const char *name);
