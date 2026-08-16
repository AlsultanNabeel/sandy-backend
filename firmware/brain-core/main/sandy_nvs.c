#include "sandy_nvs.h"
#include <string.h>
#include "nvs_flash.h"
#include "nvs.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include "config.h"

static const char *TAG      = "nvs";
static const char *NVS_NS   = "sandy";
static const char *KEY_SERVO = "servo_pos";

// ── Deferred writes ──────────────────────────────────────────────────────────
// Rationale in sandy_nvs.h. In short: an NVS commit stops both CPUs for as long
// as the erase takes, and doing that on every neck movement is what has been
// resetting this board.

#define DEFER_SLOTS      8       // more keys than this project has settings
#define DEFER_QUIET_MS   4000    // stillness required before anything is written
#define DEFER_TICK_MS    500

typedef struct {
    const char     *ns;          // namespace; string literal, never freed
    const char     *key;         // string literal from the caller; never freed
    nvs_val_kind_t  kind;
    int32_t         value;
    int64_t         changed_ms;
    bool            pending;
} defer_slot_t;

static defer_slot_t      s_slots[DEFER_SLOTS];
static SemaphoreHandle_t s_slots_lock;

static int64_t now_ms(void) { return esp_timer_get_time() / 1000; }

// Write one slot. Reads first and skips an identical value: the cheapest commit
// is the one that does not happen, and re-saving 90 degrees over 90 degrees
// still erases a sector.
static void flush_slot(defer_slot_t *sl) {
    nvs_handle_t h;
    if (nvs_open(sl->ns, NVS_READWRITE, &h) != ESP_OK) return;

    bool same = false;
    if (sl->kind == NVS_VAL_U8) {
        uint8_t cur;
        same = (nvs_get_u8(h, sl->key, &cur) == ESP_OK && cur == (uint8_t)sl->value);
    } else {
        int32_t cur;
        same = (nvs_get_i32(h, sl->key, &cur) == ESP_OK && cur == sl->value);
    }

    if (!same) {
        esp_err_t err = (sl->kind == NVS_VAL_U8)
            ? nvs_set_u8(h, sl->key, (uint8_t)sl->value)
            : nvs_set_i32(h, sl->key, sl->value);
        if (err == ESP_OK) err = nvs_commit(h);
        if (err != ESP_OK) ESP_LOGW(TAG, "save %s/%s failed: %s", sl->ns, sl->key, esp_err_to_name(err));
        else               ESP_LOGD(TAG, "saved %s/%s = %d", sl->ns, sl->key, (int)sl->value);
    }
    nvs_close(h);
}

static void defer_task(void *arg) {
    (void)arg;
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(DEFER_TICK_MS));
        for (int i = 0; i < DEFER_SLOTS; i++) {
            // Copy under the lock, write outside it: a commit can take hundreds
            // of milliseconds, and holding a lock that long would push the stall
            // onto whichever task next changes a setting.
            defer_slot_t copy;
            if (xSemaphoreTake(s_slots_lock, pdMS_TO_TICKS(100)) != pdTRUE) break;
            bool due = s_slots[i].pending &&
                       (now_ms() - s_slots[i].changed_ms) > DEFER_QUIET_MS;
            if (due) { copy = s_slots[i]; s_slots[i].pending = false; }
            xSemaphoreGive(s_slots_lock);
            if (due) flush_slot(&copy);
        }
    }
}

void nvs_save_deferred(const char *ns, const char *key,
                       nvs_val_kind_t kind, int32_t value) {
    if (!ns || !key || !s_slots_lock) return;
    if (xSemaphoreTake(s_slots_lock, pdMS_TO_TICKS(50)) != pdTRUE) return;
    int free_slot = -1;
    for (int i = 0; i < DEFER_SLOTS; i++) {
        if (s_slots[i].key && strcmp(s_slots[i].key, key) == 0 &&
            strcmp(s_slots[i].ns, ns) == 0) {
            // Same setting again: replace the pending value and restart the
            // quiet period. This is what turns a slider drag into one write.
            s_slots[i].value = value;
            s_slots[i].kind  = kind;
            s_slots[i].changed_ms = now_ms();
            s_slots[i].pending = true;
            xSemaphoreGive(s_slots_lock);
            return;
        }
        if (!s_slots[i].key && free_slot < 0) free_slot = i;
    }
    if (free_slot >= 0) {
        s_slots[free_slot] = (defer_slot_t){ ns, key, kind, value, now_ms(), true };
    } else {
        // Out of slots. Say so rather than dropping a setting silently — this
        // only happens if somebody adds settings without raising DEFER_SLOTS.
        ESP_LOGW(TAG, "no deferred slot for %s/%s — setting will not persist", ns, key);
    }
    xSemaphoreGive(s_slots_lock);
}

void nvs_flush_deferred(void) {
    if (!s_slots_lock) return;
    for (int i = 0; i < DEFER_SLOTS; i++) {
        defer_slot_t copy;
        if (xSemaphoreTake(s_slots_lock, pdMS_TO_TICKS(100)) != pdTRUE) return;
        bool due = s_slots[i].pending;
        if (due) { copy = s_slots[i]; s_slots[i].pending = false; }
        xSemaphoreGive(s_slots_lock);
        if (due) flush_slot(&copy);
    }
}


esp_err_t nvs_sandy_init(void) {
    esp_err_t err = nvs_flash_init();
    if (err == ESP_ERR_NVS_NO_FREE_PAGES || err == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_LOGW(TAG, "partition truncated — erasing");
        ESP_ERROR_CHECK(nvs_flash_erase());
        err = nvs_flash_init();
    }
    if (err == ESP_OK) {
        s_slots_lock = xSemaphoreCreateMutex();
        // 3072: it sleeps, compares integers, and calls nvs_commit. Priority 1 —
        // below everything that matters. A setting arriving a second late costs
        // nothing; a setting written during a wake word cost six months.
        xTaskCreate(defer_task, "nvs_defer", 3072, NULL, 1, NULL);
    }
    return err;
}

esp_err_t nvs_load_servo_angle(uint8_t *out_angle) {
    nvs_handle_t h;
    esp_err_t err = nvs_open(NVS_NS, NVS_READONLY, &h);
    if (err != ESP_OK) return err;
    err = nvs_get_u8(h, KEY_SERVO, out_angle);
    nvs_close(h);
    return err;
}
