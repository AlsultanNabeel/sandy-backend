#pragma once
#include <stdbool.h>

// One heavy TLS session at a time: internal RAM fits one handshake plus the voice
// pipeline, and OTA + voice together rebooted the board. Lock-free, never blocks.
typedef enum {
    NET_OWNER_NONE  = 0,
    NET_OWNER_VOICE = 1,   // voice session: from the wake word to ws_close
    NET_OWNER_OTA   = 2,   // update check: manifest fetch and download
} net_owner_t;

// True if `owner` now holds the network (or already did).
bool        net_claim(net_owner_t owner);
// Releases only if `owner` holds it; a release by the wrong owner is a no-op.
void        net_release(net_owner_t owner);
net_owner_t net_owner(void);
