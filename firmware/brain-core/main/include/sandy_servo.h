#pragma once
#include <stdint.h>
#include "esp_err.h"
#include <stdbool.h>

esp_err_t servo_init(void);
// Turn to an angle (clamped, sine-eased) on the neck's own task. Returns at
// once: the easing takes ~20 ms per degree, and the mic task that calls this
// after the wake word must never wait for it. Replaces any gesture in progress.
void      servo_move_to(uint8_t angle);
uint8_t   servo_get_angle(void);

// ── Gestures ─────────────────────────────────────────────────────────────────
//
// A neck that only goes to an angle is a positioner. A neck that nods, shakes
// and sways is a face with a body attached — and the difference costs about
// thirty lines, because the easing is already there.
//
// A gesture is a list of (angle, hold) steps played on a background task, so
// nothing that has to stay real-time ever waits for a servo. Starting a new one
// replaces whatever was playing: the last thing asked for is what she does, and
// a queue of stale gestures acting out minutes later is worse than none.
//
// Every gesture returns to where it started, so a nod during a conversation does
// not slowly walk her head off to one side over an evening.
typedef enum {
    GESTURE_NONE = 0,
    GESTURE_NOD,        // yes — two dips
    GESTURE_SHAKE,      // no — side to side
    GESTURE_TILT,       // curious — lean and hold, then straighten
    GESTURE_SCAN,       // sweep the room once, slowly
    GESTURE_DANCE,      // playful sway, four beats
    GESTURE_WAKE,       // a small startle then settle: she just heard her name
    GESTURE_SLEEP,      // droop, slowly
    GESTURE_LOOK_LEFT,
    GESTURE_LOOK_RIGHT,
    GESTURE_CENTER,
    GESTURE_COUNT
} sandy_gesture_t;

// Play one. Non-blocking; replaces any gesture in progress.
void servo_gesture(sandy_gesture_t g);

