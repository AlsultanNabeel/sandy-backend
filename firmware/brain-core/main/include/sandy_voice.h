#pragma once
#include "esp_err.h"
#include <stdbool.h>

// Real-time voice link to the cloud (/voice WebSocket + Gemini Live).
//
// Brings up two I2S channels (INMP441 mic in, MAX98357 amp out), connects to
// the server, does the HMAC handshake, then streams mic audio up and plays
// Sandy's audio back down. While she talks the uplink is gated (echo canceller
// plus a sustained-speech bar), which is what lets a person interrupt her.
//
// Call once after Wi-Fi is up. Safe to skip if the voice hardware isn't wired.
esp_err_t voice_init(void);

// True once the server accepted the handshake (auth_ok) and the link is live.
bool voice_is_connected(void);

// True while a voice conversation is in progress (wake word heard and the
// session not yet idle-closed). Other subsystems should leave the face and
// neck alone while this is true.
bool voice_session_is_active(void);

// Play locally generated PCM (24 kHz — her voice's rate — 16-bit, mono) through the speaker by
// pushing it into the same buffer the cloud audio uses. Returns false if the
// buffer is full. Used by the speaker test tone: going through this path rather
// than opening a second I2S channel means a successful beep proves the real
// output path — buffer, volume and amp — not a parallel one that happens to work.
bool voice_play_local_pcm(const int16_t *pcm, size_t bytes);

// How loud the speaker is right now, 0..100 — what the amp is playing this
// instant, for the face: her mouth moves with her voice.
int voice_output_level(void);
