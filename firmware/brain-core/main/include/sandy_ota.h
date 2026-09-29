#pragma once
#include "esp_err.h"
#include <stdbool.h>

esp_err_t ota_init(void);

// Signed OTA pull: first check a minute after boot, then every six hours.
void      ota_updates_start(void);
// Check now (MQTT "ota" command); only signed manifest releases are installed.
void      ota_check_now(void);

// Rollback: a new image boots PENDING_VERIFY and is confirmed once Wi-Fi associates
// (still rescuable over the air), not on cloud reachability or full init. Call after remote_init().
void      ota_start_health_watch(void);

