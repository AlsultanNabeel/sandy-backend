#pragma once

#include <stdbool.h>
#include <stddef.h>

// Keeping her alive unattended: the task watchdog for the tasks that matter, and
// safe mode when she keeps crashing.

// First thing at boot: reads why she restarted and counts crash restarts in a row.
// Three of them within the stable window (config.h) and she boots in safe mode.
void health_boot(void);
bool health_safe_mode(void);

// Starts the monitor (internal RAM, a LOW_MEMORY left standing). After the settings store.
void health_init(void);

// The heartbeat's health members, without braces: why she last restarted, restarts
// since the first boot, the least internal RAM she has had, its largest block now,
// safe mode, every part not OK, and each task's least stack headroom in bytes.
// Returns the length, or -1 if it does not fit.
int health_json(char *out, size_t cap);

// A clean restart: deferred settings saved first. Counts as a crash for safe mode.
void health_restart(const char *why) __attribute__((noreturn));

// The calling task is now watched: it must call health_feed() at least every
// CONFIG_ESP_TASK_WDT_TIMEOUT_S, or the board restarts (CONFIG_ESP_TASK_WDT_PANIC).
void health_watch(void);
void health_feed(void);

// Around a wait that is long on purpose (a TLS handshake or teardown, an update):
// the task leaves the watchdog and comes back after. Never around a loop.
void health_unwatch(void);
