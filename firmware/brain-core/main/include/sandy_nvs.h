#pragma once
#include <stdint.h>
#include "esp_err.h"

esp_err_t nvs_sandy_init(void);
esp_err_t nvs_load_servo_angle(uint8_t *out_angle);

// ── Deferred settings writes ─────────────────────────────────────────────────
//
// Nothing on a hot path may write flash directly, and this is why.
//
// An NVS commit erases and rewrites flash. While that happens the CPU cache is
// off, so any code living in flash stalls — on both cores. Usually that is a few
// milliseconds and nobody notices. But this partition is 20 KB, five sectors,
// and the neck used to save its angle on EVERY movement: once per wake word as
// she turned toward the voice, and once per step of a gesture — seven writes for
// one dance. A partition that small fills fast, and a full commit then triggers
// a garbage-collection pass that erases several sectors in a row.
//
// When that pass runs longer than 300 ms, the interrupt watchdog fires. And
// because the cache is off, the panic handler cannot run either — so the chip
// takes the watchdog's second stage and resets with no message at all. A silent
// reboot, right when she was moving and listening, which is exactly when it is
// most maddening.
//
// So writes are queued instead. Repeated calls with the same key overwrite the
// pending value rather than adding another write, and nothing reaches flash
// until the value has been still for a few seconds. Dragging a slider across its
// whole range is one write. A dance is one write, of where the head ended up.
//
// Safe from any task; it only touches a small RAM table under a mutex.
typedef enum { NVS_VAL_U8, NVS_VAL_I32 } nvs_val_kind_t;

// `ns` is the NVS namespace, and it is a parameter rather than a constant
// because this project has two: the neck saves under "sandy", the audio settings
// under "sandy_audio". Writing one into the other loses the value in silence —
// it saves without error and reads back as absent on the next boot.
//
// Both `ns` and `key` must outlive the call. String literals, in practice; the
// table stores the pointers and never copies or frees them.
void nvs_save_deferred(const char *ns, const char *key,
                       nvs_val_kind_t kind, int32_t value);

// Flush anything pending right now. For shutdown paths — normal code should let
// the quiet period do it.
void nvs_flush_deferred(void);
