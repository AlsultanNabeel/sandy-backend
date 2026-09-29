#pragma once
#include "esp_err.h"

// Infrared learn and replay. Raw pulse capture (no protocol decoding) so any remote works.
// Output `ir`: "learn" arms the receiver and publishes the next press to
// sandy/node/<id>/ir/learned; any other payload is a recorded code to replay.
// Gated by ENABLE_IR in config.h.
esp_err_t ir_init(void);

// Safe to call from the MQTT task.
void ir_handle(const char *payload);
