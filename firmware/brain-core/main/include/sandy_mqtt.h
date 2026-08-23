#pragma once
#include <stdbool.h>
#include "esp_err.h"

esp_err_t mqtt_sandy_start(void);
void      mqtt_publish_status(void);    // call manually if needed; auto every 5s

// Publish under this robot's own tree: sandy/node/<id>/<suffix>.
// Used for reports the board makes about itself — a learned IR code, for
// instance — as opposed to commands, which arrive rather than leave.
bool      mqtt_publish_node(const char *suffix, const char *payload);

// Drive one room output from a local command word — `out` is the bare name
// ("light", "fan", "music"), and the topic is built under this robot's own tree
// as sandy/node/<id>/room/<out>. Passing a full topic here is a bug: it would
// arrive as sandy/node/<id>/room/room/cmd/light and nothing would listen.
// No-op (returns false) if the MQTT client isn't connected yet.
bool      mqtt_publish_room(const char *out, const char *payload);

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
