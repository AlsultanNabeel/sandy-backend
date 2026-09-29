#pragma once
#include <stdbool.h>
#include "esp_err.h"

esp_err_t mqtt_sandy_start(void);
void      mqtt_publish_status(void);    // call manually if needed; auto every 5s

// Publish to sandy/node/<id>/<suffix>.
bool      mqtt_publish_node(const char *suffix, const char *payload);

// Publish to sandy/node/<id>/room/<out>; `out` is the bare name ("light"), not a topic.
// Returns false if MQTT isn't connected.
bool      mqtt_publish_room(const char *out, const char *payload);

// Store this board's own broker login (sent in the voice handshake) and use it.
// Returns true only if it changed; identical values are not rewritten, to spare flash.
bool      mqtt_sandy_set_credentials(const char *user, const char *pass);
