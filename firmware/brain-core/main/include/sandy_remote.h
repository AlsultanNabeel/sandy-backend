#pragma once
#include "esp_err.h"

// Dev over Wi-Fi: POST a .bin to http://<ip>/update; log stream on `nc <ip> 3333`.
// Gated by ENABLE_REMOTE in config.h.
esp_err_t remote_init(void);

// The setup page takes port 80 while it is up: release stops the upload server (and keeps
// it from starting), resume starts it again once there is a network.
void remote_http_release(void);
void remote_http_resume(void);
