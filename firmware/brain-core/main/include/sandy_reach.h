#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Whether Sandy's server can be reached from this network, not only the router: a phone
// hotspot with no data or a hotel's sign-in page gives an address and goes nowhere.

typedef enum {
    REACH_OK = 0,   // the server answered over TLS, its real certificate
    REACH_FAIL,     // no answer from this network
    REACH_BUSY,     // a call or an update holds the network now; ask later
    REACH_UNSET,    // no server address on this board (not set up): nothing to ask
} reach_t;

// Something reached the server just now: the broker, a call, an update check.
void    reach_mark(void);
// When that last happened, on the uptime clock in ms; 0 = never since boot.
int64_t reach_last_ms(void);
// Asks the server once (GET /health); blocks for up to its eight-second deadline.
reach_t reach_probe(void);
// "https://<host>" of the voice server, which is also the update and API server.
bool    reach_api_base(char *out, size_t cap);
