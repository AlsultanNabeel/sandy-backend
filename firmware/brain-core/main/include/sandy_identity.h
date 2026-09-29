#pragma once
#include <stdbool.h>
#include "esp_err.h"

// Robot identity. The image carries none of it; each value comes from, in order:
//   1. secrets.h with a real value (cable flash), also saved to NVS
//   2. the factory partition `fctry` (scripts/provision_brain.py)
//   3. NVS `sandyid` from an earlier boot
// Placeholders are never values and never overwrite one.

typedef struct {
    char pair_code[24];     // printed on the box
    char node_id[33];       // lowercase alphanumerics of pair_code
    char device_id[33];     // voice socket id; must equal node_id
    char mqtt_uri[128];
    char mqtt_user[65];
    char mqtt_pass[129];
    char voice_uri[128];    // wss://…/voice
    char hmac_key[80];      // shared key until the board gets its own
    char wifi_ssid[33];     // first network, before setup saves the owner's
    char wifi_pass[65];
} sandy_identity_t;

// After nvs_flash_init. Never fails hard; logs what is missing.
esp_err_t identity_init(void);

const sandy_identity_t *identity(void);

// The factory reset calls this after erasing NVS: forget the owner, not the identity.
esp_err_t identity_save(void);

bool identity_complete(void);
