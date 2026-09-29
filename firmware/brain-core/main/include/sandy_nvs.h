#pragma once
#include <stdint.h>
#include "esp_err.h"

esp_err_t nvs_sandy_init(void);
esp_err_t nvs_load_servo_angle(uint8_t *out_angle);

// Deferred settings writes. An NVS commit disables the flash cache on both cores;
// frequent writes to this small partition triggered GC long enough to fire the
// interrupt watchdog and silently reset. Writes are coalesced per key and flushed
// after a few quiet seconds. Safe from any task.
typedef enum { NVS_VAL_U8, NVS_VAL_I32 } nvs_val_kind_t;

// `ns` matters: the neck uses "sandy", audio "sandy_audio"; the wrong one saves
// silently and reads back absent. `ns` and `key` must outlive the call (pointers are stored).
void nvs_save_deferred(const char *ns, const char *key,
                       nvs_val_kind_t kind, int32_t value);

// For shutdown paths only.
void nvs_flush_deferred(void);
