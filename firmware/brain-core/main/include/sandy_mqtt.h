#pragma once
#include <stdbool.h>
#include "esp_err.h"

esp_err_t mqtt_sandy_start(void);
void      mqtt_publish_status(void);    // call manually if needed; auto every 5s

// Publish a raw retained-0/QoS-0 message to any topic on the shared broker.
// Used by local command words to drive the room node (e.g. "room/cmd/light").
// No-op (returns false) if the MQTT client isn't connected yet.
bool      mqtt_publish_room(const char *topic, const char *payload);

// Store this board's own broker login and start using it.
//
// Called from the voice handshake, which is where the server hands a board the
// credential issued to it alone — over a link authenticated with a different
// key, so it keeps working after the shared broker login is revoked.
//
// Returns true only when something actually changed: an identical credential is
// not rewritten, because the handshake happens every voice session and a write
// per session would wear the flash out for nothing.
bool      mqtt_sandy_set_credentials(const char *user, const char *pass);
