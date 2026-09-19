#pragma once
#include "esp_err.h"
#include <stdbool.h>

esp_err_t ota_init(void);

// Signed over-the-air updates pulled from the server (see sandy_ota.c): a first
// check a minute after boot, then every six hours. Call once, after Wi-Fi.
void      ota_updates_start(void);
// Check for a release now (the MQTT "ota" command). The payload is ignored: the
// board only ever installs what the manifest lists and the owner's key signed.
void      ota_check_now(void);

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
// Healthy means **still rescuable**, nothing more: Wi-Fi associated, so it can
// fetch the next release. Not "the cloud answers" — tie it to that and a home
// internet outage rolls back perfectly good firmware. Not "everything
// initialised" either; a robot with a broken servo but a working uplink is a
// robot you can fix remotely, and rolling it back would throw away the fix.
//
// Start this once, after remote_init(). It is a no-op on an image that has
// already been confirmed, so it costs nothing on an ordinary boot.
void      ota_start_health_watch(void);

