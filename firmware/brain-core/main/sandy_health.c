// The task watchdog, for the tasks whose hang would leave her deaf or frozen, and the
// boot-loop guard (contract in sandy_health.h).

#include "sandy_health.h"

#include "config.h"
#include "esp_attr.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_task_wdt.h"
#include "esp_timer.h"
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "nvs.h"
#include "sandy_nvs.h"
#include "sandy_status.h"
#if ENABLE_VOICE
#include "sandy_voice.h"
#endif

static const char *TAG = "health";

// ── Boot-loop guard ──
// RTC memory survives every restart but a power cut, which is exactly the span to
// count: a cold start is a fresh chance.
#define GUARD_MAGIC 0x5A4E4459u   // "SNDY"
typedef struct {
    uint32_t magic;
    uint32_t crashes;   // crash restarts in a row, none followed by a stable run
    uint32_t ours;      // health_restart() was the last restart
} guard_t;
static RTC_NOINIT_ATTR guard_t s_guard;

static bool s_safe;
static uint32_t s_boots;   // restarts since the first boot, from the settings store

// Tasks whose stack headroom the heartbeat reports: ours, and the libraries' that carry
// the network. A name not running (feature off, not started yet) is skipped.
static const char *const STACK_TASKS[] = {
    "main", "voice", "voice_mic", "voice_proc", "voice_spk", "voice_tx", "lvgl",
    "mqtt_status", "mqtt_task", "websocket_task", "wifi_retry", "ota_health", "ota_check",
    "servo_gest", "buzzer", "led_fx", "nvs_defer", "ir_rx", "provision", "health",
};

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
        s_guard.ours = 0;
    }
    const bool ours = r == ESP_RST_SW && s_guard.ours;
    s_guard.ours = 0;
    if (is_crash(r) || ours) s_guard.crashes++;
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

void health_restart(const char *why) {
    ESP_LOGE(TAG, "restarting: %s", why);
    s_guard.ours = 1;
    nvs_flush_deferred();
    vTaskDelay(pdMS_TO_TICKS(300));   // the log line out first
    esp_restart();
}

static bool in_call(void) {
#if ENABLE_VOICE
    return voice_session_is_active();
#else
    return false;
#endif
}

static bool low_memory_shown(void) {
    for (int p = 0; p < SANDY_PART_COUNT; p++) {
        if (status_part_get((sandy_part_t)p) == SANDY_ST_LOW_MEMORY) return true;
    }
    return false;
}

// Every two seconds: internal RAM, and a LOW_MEMORY that promised a restart.
static void monitor_task(void *arg) {
    (void)arg;
    int64_t low_since = 0, status_since = 0;
    health_watch();
    for (;;) {
        health_feed();
        vTaskDelay(pdMS_TO_TICKS(2000));
        const int64_t now = esp_timer_get_time() / 1000;
        const size_t free_b = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
        const size_t big = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);

        if (free_b < HEALTH_HEAP_DANGER || big < HEALTH_BLOCK_DANGER) {
            if (!low_since) {
                low_since = now;
                ESP_LOGW(TAG, "internal RAM low: free=%u largest=%u",
                         (unsigned)free_b, (unsigned)big);
            }
        } else {
            low_since = 0;
        }
        status_since = low_memory_shown() ? (status_since ? status_since : now) : 0;

        // Never mid-call: a dropped call is worse than waiting for it to end.
        if (in_call()) continue;
        if (low_since && now - low_since > HEALTH_LOW_MEM_MS) {
            status_set(SANDY_PART_SYSTEM, SANDY_ST_LOW_MEMORY);
            health_restart("internal RAM stayed low");
        }
        if (status_since && now - status_since > HEALTH_LOW_STATUS_MS) {
            health_restart("out of memory, as she said");
        }
    }
}

// One NVS write per boot: the count survives power cuts, unlike the crash guard.
static void count_boot(void) {
    nvs_handle_t h;
    if (nvs_open("sandy", NVS_READWRITE, &h) != ESP_OK) return;
    if (nvs_get_u32(h, "boots", &s_boots) != ESP_OK) s_boots = 0;
    s_boots++;
    if (nvs_set_u32(h, "boots", s_boots) == ESP_OK) nvs_commit(h);
    nvs_close(h);
}

int health_json(char *out, size_t cap) {
    char faults[160];
    status_faults_json(faults, sizeof(faults));
    int k = snprintf(out, cap,
                     "\"boot\":%d,\"boots\":%lu,\"heap_min\":%u,\"heap_big\":%u,"
                     "\"safe\":%s,\"faults\":{%s},\"stacks\":{",
                     (int)esp_reset_reason(), (unsigned long)s_boots,
                     (unsigned)heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL),
                     (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
                     s_safe ? "true" : "false", faults);
    if (k < 0 || k >= (int)cap) return -1;
    bool first = true;
    for (size_t i = 0; i < sizeof(STACK_TASKS) / sizeof(STACK_TASKS[0]); i++) {
        TaskHandle_t t = xTaskGetHandle(STACK_TASKS[i]);
        if (!t) continue;
        int n = snprintf(out + k, cap - k, "%s\"%s\":%u", first ? "" : ",",
                         STACK_TASKS[i], (unsigned)uxTaskGetStackHighWaterMark(t));
        if (n < 0 || n >= (int)(cap - k)) return -1;
        k += n;
        first = false;
    }
    if (k + 2 > (int)cap) return -1;
    out[k++] = '}';
    out[k] = '\0';
    return k;
}

void health_init(void) {
    count_boot();
    // Internal stack: health_restart() saves settings, and flash writes disable PSRAM.
    if (xTaskCreate(monitor_task, "health", 3072, NULL, 2, NULL) != pdPASS) {
        ESP_LOGE(TAG, "health monitor did not start");
    }
}
