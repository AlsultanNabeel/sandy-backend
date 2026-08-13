#pragma once
#include "sandy_types.h"
#include "esp_err.h"

// Phase 0 stub — full LVGL implementation in Phase 0 V0.11
esp_err_t face_init(void);
void      face_set_mood(sandy_mood_t mood);

// Glance the eyes toward a sound. pan: -100 = hard left, 0 = centre, +100 = right.
// The gaze holds briefly then drifts back to idle on its own.
void      face_look(int pan);

// Focus-session countdown ring. phase: 0 = off, 1 = focus, 2 = break.
// Called from the MQTT task — it only stores state; the LVGL task draws the
// ring, alternating it with the normal face (≈5 s on / 5 s off).
void      face_set_focus(int phase, int remaining_sec, int total_sec);

