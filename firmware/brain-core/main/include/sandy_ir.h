#pragma once
#include "esp_err.h"

// Infrared learn and replay — the cheapest large feature on the robot.
//
// A receiver and an LED that cost about a dollar and a half turn every remote in
// the room into something she can press: the television, the air conditioner, the
// fan. No relays, no wiring into the mains, no second board. The backend half has
// been complete for a while — a learn topic, an endpoint, a device type — and
// this is the board half it was waiting for.
//
// **Raw capture, not protocol decoding.** She records the pulse train exactly as
// it arrives and replays it exactly as recorded, so a remote whose protocol
// nobody has implemented still works. Decoding would be the smaller-sounding job
// and the one that fails on the customer's air conditioner.
//
// One output, `ir`, with two payloads:
//   "learn"  → arm the receiver; the next remote press is published to
//              sandy/node/<id>/ir/learned and the backend stores it
//   anything else → treat it as a recorded code and replay it
//
// Gated by ENABLE_IR in config.h.
esp_err_t ir_init(void);

// Handle one payload on the `ir` output. Safe to call from the MQTT task.
void ir_handle(const char *payload);
