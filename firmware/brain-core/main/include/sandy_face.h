#pragma once
#include "sandy_types.h"
#include "esp_err.h"
#include <stdbool.h>

// Phase 0 stub — full LVGL implementation in Phase 0 V0.11
esp_err_t face_init(void);
void      face_set_mood(sandy_mood_t mood);

// Glance the eyes toward a sound. pan: -100 = hard left, 0 = centre, +100 = right.
// The gaze holds briefly then drifts back to idle on its own.
void      face_look(int pan);

// Tell the face whether a conversation is actually in progress.
//
// This is the guarantee that she cannot freeze mid-expression again. The wake
// word puts a transient face on (curious, listening, talking) and something
// downstream is supposed to take it off. Once, the code that took it off lived
// only on the success path, so a failed connection left her staring — awake to
// look at, deaf in fact — until someone pulled the power.
//
// Fixing that one path was not enough: the next path added could forget in
// exactly the same way. So the face no longer trusts anyone to clean up after
// themselves. It watches: a transient expression that outlives its session gets
// dropped, whatever it was that failed to clear it and whether or not anybody
// remembered this rule existed.
//
// Call it with true when a voice session opens, false when it closes. Missing a
// `false` is safe — that is the entire point.
void      face_set_session_active(bool active);

// A short status line across the bottom of the face — "NO WI-FI", "SLOW NET".
// Pass "" to clear it. Latin only: Montserrat is the sole font in this build and
// it carries no Arabic glyphs. Called from any task (Wi-Fi events, the websocket
// callback); it only stores the string, the LVGL task draws it.
void      face_set_banner(const char *text);

// Focus-session countdown ring. phase: 0 = off, 1 = focus, 2 = break.
// Called from the MQTT task — it only stores state; the LVGL task draws the
// ring, alternating it with the normal face (≈5 s on / 5 s off).
void      face_set_focus(int phase, int remaining_sec, int total_sec);

