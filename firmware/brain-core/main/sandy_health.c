// The task watchdog, for the tasks whose hang would leave her deaf or frozen
// (contract in sandy_health.h). Each one feeds it from its own loop.

#include "sandy_health.h"

#include "esp_log.h"
#include "esp_task_wdt.h"

static const char *TAG = "health";

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
