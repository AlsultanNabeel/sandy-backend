#pragma once
#include <stdbool.h>
#include "esp_err.h"

// ── Who this robot is ────────────────────────────────────────────────────────
//
// The pairing code, the broker login, the voice key and the first Wi-Fi used to
// be compiled into the image from secrets.h. That is fine while every robot is
// flashed by cable one at a time, and wrong the moment updates go over the air:
// one image goes to every robot, so it either carries one robot's identity to
// all of them or wipes theirs — and the image sits on a public endpoint, so any
// secret in it is everyone's.
//
// Now the image carries none of it. Each value comes from, in order:
//   1. secrets.h, when it holds a real value — a developer's cable flash. The
//      value is also saved to NVS, so the next image can do without it.
//   2. the factory partition (`fctry`, namespace `sandy_id`) — written once per
//      unit at production by scripts/provision_brain.py.
//   3. what an earlier boot saved in NVS (`sandyid`).
// A placeholder ("YOUR_…", "…XXXX…", empty) is never a value, and never
// overwrites one. The retail build compiles secrets.example.h, so an update
// image is identical for every robot and holds nothing private.

typedef struct {
    char pair_code[24];     // printed on the box
    char node_id[33];       // pair_code, lowercase alphanumerics — the topic tree
    char device_id[33];     // voice socket id; must equal node_id
    char mqtt_uri[128];
    char mqtt_user[65];
    char mqtt_pass[129];
    char voice_uri[128];    // wss://…/voice
    char hmac_key[80];      // shared voice key until the board gets its own
    char wifi_ssid[33];     // first network, before setup saves the owner's
    char wifi_pass[65];
} sandy_identity_t;

// After nvs_flash_init. Never fails hard: a board without an identity still
// boots, shows setup, and says in the log what it is missing.
esp_err_t identity_init(void);

const sandy_identity_t *identity(void);

// Write the identity in use back to NVS. The factory reset erases all of NVS
// and calls this: the robot forgets its owner, not what it is.
esp_err_t identity_save(void);

// Enough to join the fleet: a pairing code, a broker and a voice server.
bool identity_complete(void);
