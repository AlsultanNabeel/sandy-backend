#pragma once
#include "esp_err.h"
#include <stdbool.h>

esp_err_t ota_init(void);
void      ota_trigger(const char *url);   // called from MQTT handler

// ── Rollback ─────────────────────────────────────────────────────────────────
//
// With CONFIG_BOOTLOADER_APP_ROLLBACK_ENABLE, a freshly flashed image boots as
// PENDING_VERIFY: it has to declare itself healthy, or the next reboot puts the
// previous image back.
//
// The point is that firmware here arrives over Wi-Fi. One bad image that boots
// but cannot reach the network would otherwise take the only recovery path with
// it, and the way back is a cable and an opened case. This turns that into a
// robot that reboots once and comes back on the version that worked.
//
// Healthy means **still rescuable**, nothing more: Wi-Fi associated and the
// update server listening. Not "the cloud answers" — tie it to that and a home
// internet outage rolls back perfectly good firmware. Not "everything
// initialised" either; a robot with a broken servo but a working uplink is a
// robot you can fix remotely, and rolling it back would throw away the fix.
//
// Start this once, after remote_init(). It is a no-op on an image that has
// already been confirmed, so it costs nothing on an ordinary boot.
void      ota_start_health_watch(void);

// True once this image has been confirmed (or was never pending).
bool      ota_image_confirmed(void);
