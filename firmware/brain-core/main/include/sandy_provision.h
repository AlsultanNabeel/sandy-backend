#pragma once
#include <stdbool.h>
#include "esp_err.h"

// First-run Wi-Fi setup: with no network, raise an AP named after the box code,
// serve a network picker, test the credentials before saving, then reboot.
// Triggers: no network within PROVISION_WINDOW_MS of boot, or the owner asks.
// Call once, after wifi_sandy_start(). Gated by ENABLE_PROVISION in config.h.
esp_err_t provision_init(void);

// True while the setup AP is up; voice and MQTT stay quiet so the setup screen stays clear.
bool provision_is_active(void);
