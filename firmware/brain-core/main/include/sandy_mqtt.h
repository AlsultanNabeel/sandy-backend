#pragma once
#include <stdbool.h>
#include "esp_err.h"

esp_err_t mqtt_sandy_start(void);
void      mqtt_publish_status(void);    // call manually if needed; auto every 5s

// Publish a raw retained-0/QoS-0 message to any topic on the shared broker.
// Used by local command words to drive the room node (e.g. "room/cmd/light").
// No-op (returns false) if the MQTT client isn't connected yet.
bool      mqtt_publish_room(const char *topic, const char *payload);
