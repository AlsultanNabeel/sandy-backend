#pragma once
#include "sandy_types.h"
#include "esp_err.h"
#include <stdbool.h>

esp_err_t face_init(void);
void      face_set_mood(sandy_mood_t mood);
// An app-chosen mood; the stuck-expression watchdog leaves it alone until
// FACE_APP_MOOD_TTL_MS or the robot's own next expression.
void      face_set_mood_from_app(sandy_mood_t mood);

// pan: -100 left, 0 centre, +100 right. Drifts back to idle on its own.
void      face_look(int pan);

// Transient expressions that outlive their session are dropped by the face itself,
// so a missed `false` (e.g. on a failure path) can't leave her frozen.
void      face_set_session_active(bool active);

// Status line at the bottom ("" clears). Latin only: the font has no Arabic.
// Any task may call it; the LVGL task draws.
void      face_set_banner(const char *text);

// Focus countdown ring. phase: 0 off, 1 focus, 2 break. Only stores state;
// the LVGL task alternates it with the face.
void      face_set_focus(int phase, int remaining_sec, int total_sec);

