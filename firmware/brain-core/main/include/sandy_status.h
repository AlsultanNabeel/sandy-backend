#pragma once
#include <stdbool.h>
#include <stddef.h>

// Health surface: subsystems report via status_set(); this module alone turns it
// into face, LED, text and speech, so no failure is silent.

typedef enum {
    SANDY_ST_OK = 0,        // everything reachable
    SANDY_ST_BOOTING,       // still bringing subsystems up
    SANDY_ST_NO_WIFI,       // no association with the access point
    SANDY_ST_NO_SERVER,     // Wi-Fi up, the cloud is not answering
    SANDY_ST_LINK_DROPPED,  // connected, then died mid-conversation
    SANDY_ST_NET_SLOW,      // audio stuck AND weak radio
    // Audio stuck but radio is strong: a different fix than "move closer".
    SANDY_ST_LINK_STALL,
    SANDY_ST_AUTH_FAILED,   // server refused this device
    SANDY_ST_LOW_MEMORY,    // not enough internal RAM to open a session
    // Router refused the password (distinct from NO WI-FI).
    SANDY_ST_WIFI_BAD_PASS,
    SANDY_ST_SETTINGS_OFF,  // the settings store could not be opened: running on defaults
    SANDY_ST_VOICE_OFF,     // mic, speaker or the audio front end did not start
    SANDY_ST_NECK_OFF,      // the neck could not start
    SANDY_ST_SCREEN_OFF,    // the display did not start (heartbeat and LED only, obviously)
    SANDY_ST_SAFE_MODE,     // crashed repeatedly: network and updates only
    SANDY_ST_COUNT
} sandy_status_t;

// Each part owns its own status, so one recovering never clears another's fault.
// What she shows is the most serious of them.
typedef enum {
    SANDY_PART_SYSTEM = 0,  // boot
    SANDY_PART_NET,         // Wi-Fi
    SANDY_PART_LINK,        // the voice server and the uplink
    SANDY_PART_VOICE,       // mic, speaker, audio front end
    SANDY_PART_SETTINGS,    // the settings store (NVS)
    SANDY_PART_NECK,
    SANDY_PART_SCREEN,
    SANDY_PART_COUNT
} sandy_part_t;

// Safe before the display exists; text is drawn once the face is ready.
void status_init(void);

// Re-reporting the same status for a part doesn't re-announce it.
void status_set(sandy_part_t part, sandy_status_t st);

// The status shown: the most serious across parts.
sandy_status_t status_get(void);

sandy_status_t status_part_get(sandy_part_t part);

// Every part not OK, as JSON members (`"net":"no_wifi",…`), for the heartbeat.
// Returns the length written; 0 when all are OK.
int status_faults_json(char *out, size_t cap);
