#pragma once
#include <stdbool.h>

// One heavy TLS session at a time.
//
// Internal RAM holds one TLS handshake plus the voice pipeline, not two. An
// update check (HTTPS, possibly a ~1.9 MB download) and a voice session (WSS)
// opened together exhausted it and rebooted the board. Whoever wants either one
// claims this first and releases it when its connection is gone.
//
// Lock-free (one atomic compare-and-swap), so it is safe from any task and
// never blocks. A claim that fails means "someone else is on the network" —
// the caller decides whether to wait, retry later or give up.
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
