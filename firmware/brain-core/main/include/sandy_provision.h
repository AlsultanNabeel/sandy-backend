#pragma once
#include <stdbool.h>
#include "esp_err.h"

// First-run network setup, without a cable and without a rebuild.
//
// The Wi-Fi name and password used to be compiled in. That is fine for one
// board on one desk and it is **not a product**: every customer would need a
// source edit, a toolchain, and a flash — from you, for their house. It also has
// no answer for the ordinary case of somebody changing their router, which the
// old code met by retrying the dead network for ever, silently.
//
// So when the robot cannot reach a network, it becomes one. It raises an access
// point named after the code printed on its box, serves a page listing the
// networks it can see, takes the one the owner picks, proves the credentials
// work *before* keeping them, and reboots onto the network.
//
// Two triggers, and the second is the one that matters in a house:
//   • no network reaches us within PROVISION_WINDOW_MS of boot
//   • the owner asks for it (a long press, or the app, later)
//
// Call once, after wifi_sandy_start(). Gated by ENABLE_PROVISION in config.h.
esp_err_t provision_init(void);

// True while the access point is up and the setup page is being served. The
// voice and MQTT paths use it to stay quiet: a robot in setup has no cloud, and
// error banners about a server it was never going to reach are noise at the
// exact moment the owner needs one clear instruction on the screen.
bool provision_is_active(void);
