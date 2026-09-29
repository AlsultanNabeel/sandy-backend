#pragma once
#include <stdbool.h>

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
    SANDY_ST_COUNT
} sandy_status_t;

// Safe before the display exists; text is drawn once the face is ready.
void status_init(void);

// Re-reporting the same status doesn't re-announce it.
void status_set(sandy_status_t st);

sandy_status_t status_get(void);
