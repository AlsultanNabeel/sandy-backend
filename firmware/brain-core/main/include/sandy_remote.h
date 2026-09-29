#pragma once
#include "esp_err.h"

// Dev over Wi-Fi: POST a .bin to http://<ip>/update; log stream on `nc <ip> 3333`.
// Gated by ENABLE_REMOTE in config.h.
esp_err_t remote_init(void);
