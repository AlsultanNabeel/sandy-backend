#pragma once
#include <stdint.h>
#include "esp_err.h"
#include <stdbool.h>

esp_err_t servo_init(void);
// Clamped, sine-eased move on the neck task. Returns at once (the wake-word
// mic task must not wait). Replaces any gesture in progress.
void      servo_move_to(uint8_t angle);
uint8_t   servo_get_angle(void);

// Gestures: (angle, hold) steps on a background task. A new one replaces the
// current one, and every gesture returns to where it started.
typedef enum {
    GESTURE_NONE = 0,
    GESTURE_NOD,        // yes — two dips
    GESTURE_SHAKE,      // no — side to side
    GESTURE_TILT,       // curious — lean and hold, then straighten
    GESTURE_SCAN,       // sweep the room once, slowly
    GESTURE_DANCE,      // playful sway, four beats
    GESTURE_WAKE,       // startle then settle
    GESTURE_SLEEP,      // droop, slowly
    GESTURE_LOOK_LEFT,
    GESTURE_LOOK_RIGHT,
    GESTURE_CENTER,
    GESTURE_COUNT
} sandy_gesture_t;

// Non-blocking; replaces any gesture in progress.
void servo_gesture(sandy_gesture_t g);

