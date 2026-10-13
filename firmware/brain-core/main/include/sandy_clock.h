#pragma once
#include <stdbool.h>
#include <stdint.h>

// The wall clock, set by SNTP once the board has a network: the router first, then three
// public servers. Started by app_main's loop in every mode (safe mode too), not by the voice
// task: a signed erase is checked against it, and the voice hello is signed with it.

// From app_main's loop, every second: starts SNTP once Wi-Fi is up. Never blocks.
void clock_poll(void);

// Set (post-2023) and not refused by the server since the last sync.
bool clock_ok(void);

// The server said our time is off (a `replay`): not ok until the next sync.
void clock_refuse(void);
bool clock_refused(void);

// Start SNTP over, same servers (after a refusal).
void clock_resync(void);

// When SNTP was last started, monotonic ms; 0 = not yet.
int64_t clock_started_ms(void);
