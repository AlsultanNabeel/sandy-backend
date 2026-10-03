#pragma once

#include <stdbool.h>

// Keeping her alive unattended: the task watchdog for the tasks that matter, and
// safe mode when she keeps crashing.

// First thing at boot: reads why she restarted and counts crash restarts in a row.
// Three of them within the stable window (config.h) and she boots in safe mode.
void health_boot(void);
bool health_safe_mode(void);

// The calling task is now watched: it must call health_feed() at least every
// CONFIG_ESP_TASK_WDT_TIMEOUT_S, or the board restarts (CONFIG_ESP_TASK_WDT_PANIC).
void health_watch(void);
void health_feed(void);

// Around a wait that is long on purpose (a TLS handshake or teardown, an update):
// the task leaves the watchdog and comes back after. Never around a loop.
void health_unwatch(void);
