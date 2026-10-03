// The task watchdog, for the tasks whose hang would leave her deaf or frozen, and the
// boot-loop guard (contract in sandy_health.h).

#include "sandy_health.h"

#include "config.h"
#include "esp_attr.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"

static const char *TAG = "health";

// ── Boot-loop guard ──
// RTC memory survives every restart but a power cut, which is exactly the span to
// count: a cold start is a fresh chance.
#define GUARD_MAGIC 0x5A4E4459u   // "SNDY"
typedef struct {
    uint32_t magic;
    uint32_t crashes;   // crash restarts in a row, none followed by a stable run
} guard_t;
static RTC_NOINIT_ATTR guard_t s_guard;

static bool s_safe;

static bool is_crash(esp_reset_reason_t r) {
    return r == ESP_RST_PANIC || r == ESP_RST_INT_WDT || r == ESP_RST_TASK_WDT ||
           r == ESP_RST_WDT;
}

// Ran long enough: the next crash starts the count again.
static void stable_cb(void *arg) {
    (void)arg;
    if (s_guard.crashes) ESP_LOGI(TAG, "stable for %d min — crash count cleared",
                                  HEALTH_STABLE_MS / 60000);
    s_guard.crashes = 0;
}

void health_boot(void) {
    const esp_reset_reason_t r = esp_reset_reason();
    if (s_guard.magic != GUARD_MAGIC || r == ESP_RST_POWERON) {
        s_guard.magic = GUARD_MAGIC;
        s_guard.crashes = 0;
    }
    if (is_crash(r)) s_guard.crashes++;
    else s_guard.crashes = 0;

    s_safe = s_guard.crashes >= HEALTH_SAFE_AFTER_CRASHES;
    if (s_safe) {
        ESP_LOGE(TAG, "%lu crash restarts in a row (last reason %d) — SAFE MODE: "
                      "network and updates only", (unsigned long)s_guard.crashes, (int)r);
    } else if (s_guard.crashes) {
        ESP_LOGW(TAG, "crash restart %lu of %d before safe mode (reason %d)",
                 (unsigned long)s_guard.crashes, HEALTH_SAFE_AFTER_CRASHES, (int)r);
    }

    static esp_timer_handle_t t;
    const esp_timer_create_args_t a = { .callback = stable_cb, .name = "health_stable" };
    if (esp_timer_create(&a, &t) == ESP_OK) {
        esp_timer_start_once(t, (uint64_t)HEALTH_STABLE_MS * 1000);
    }
}

bool health_safe_mode(void) {
    return s_safe;
}

void health_watch(void) {
    esp_err_t e = esp_task_wdt_add(NULL);
    if (e != ESP_OK && e != ESP_ERR_INVALID_ARG) {   // INVALID_ARG: already watched
        ESP_LOGE(TAG, "cannot watch %s (%s)", pcTaskGetName(NULL), esp_err_to_name(e));
    }
}

void health_feed(void) {
    esp_task_wdt_reset();
}

void health_unwatch(void) {
    esp_task_wdt_delete(NULL);
}
