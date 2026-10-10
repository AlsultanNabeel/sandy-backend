#pragma once
#include "config.h"
#include "esp_err.h"
#include <stdbool.h>

// Real-time voice link to the cloud (/voice WebSocket): mic up, her audio down.
// Call once after Wi-Fi is up.
esp_err_t voice_init(void);

// True once the server sent auth_ok.
bool voice_is_connected(void);

// True from the wake word until idle close; others leave the face and neck alone meanwhile.
bool voice_session_is_active(void);

// Queue local PCM (24 kHz, 16-bit mono) into the cloud audio buffer, so a test beep
// proves the real output path. Returns false if the buffer is full.
bool voice_play_local_pcm(const int16_t *pcm, size_t bytes);

// A command from the server signed like the voice hello: HMAC-SHA256 over `msg` with this
// board's own key, or the shared key while it has none. `mac_hex` is 64 hex digits.
bool voice_verify_signed(const char *msg, const char *mac_hex);

// Current speaker level 0..100, for the mouth animation.
int voice_output_level(void);

// An image is being written to flash: the echo cancelling stops (mic audio is dropped)
// until false, so the update's flash writes leave the other tasks their time. Nothing is
// lost: no call can be open while an update holds the network.
void voice_hold_for_update(bool hold);

#if ENABLE_REMOTE
// Dev only: open a session as if the wake word was heard (the echo probe's /echo/wake).
void voice_dev_wake(void);
#endif
