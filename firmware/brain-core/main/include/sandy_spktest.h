#pragma once
#include "esp_err.h"

// Speaker wiring check: repeating triple beep. Gated by ENABLE_SPK_TEST in config.h.
esp_err_t spktest_init(void);
