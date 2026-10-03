#pragma once

// Keeping her alive unattended: the task watchdog for the tasks that matter.

// The calling task is now watched: it must call health_feed() at least every
// CONFIG_ESP_TASK_WDT_TIMEOUT_S, or the board restarts (CONFIG_ESP_TASK_WDT_PANIC).
void health_watch(void);
void health_feed(void);

// Around a wait that is long on purpose (a TLS handshake or teardown, an update):
// the task leaves the watchdog and comes back after. Never around a loop.
void health_unwatch(void);
