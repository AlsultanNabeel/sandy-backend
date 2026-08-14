#include "sandy_ota.h"
#include "sandy_wifi.h"
#include "sandy_status.h"
#include "config.h"

#include "esp_https_ota.h"
#include "esp_ota_ops.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ota";

// Long enough for a slow router to hand out a lease and for the board to
// associate, short enough that a wedged image does not sit there all night
// pretending to work. Wi-Fi normally comes up in a few seconds.
#define OTA_HEALTH_TIMEOUT_MS  120000

static bool s_confirmed;

esp_err_t ota_init(void) {
    const esp_partition_t *p = esp_ota_get_running_partition();
    ESP_LOGI(TAG, "running: %s @ 0x%lx", p->label, p->address);
    return ESP_OK;
}

bool ota_image_confirmed(void) {
    return s_confirmed;
}

#if ENABLE_WIFI && ENABLE_REMOTE
static void _health_task(void *arg) {
    (void)arg;
    const int64_t start = esp_timer_get_time() / 1000;

    for (;;) {
        if (wifi_sandy_is_connected()) {
            // Rescuable: someone can push a new image at this board. Confirm,
            // and the bootloader stops watching.
            esp_err_t e = esp_ota_mark_app_valid_cancel_rollback();
            if (e == ESP_OK) {
                s_confirmed = true;
                ESP_LOGI(TAG, "image confirmed — rollback cancelled");
            } else {
                ESP_LOGW(TAG, "could not confirm image: %s", esp_err_to_name(e));
            }
            vTaskDelete(NULL);
            return;
        }

        if ((esp_timer_get_time() / 1000) - start > OTA_HEALTH_TIMEOUT_MS) {
            // Two minutes without a network. This image cannot be updated and
            // cannot be talked to, so keeping it would mean opening the case.
            // Hand back to the version that worked.
            ESP_LOGE(TAG, "no network in %d s — rolling back to the previous image",
                     OTA_HEALTH_TIMEOUT_MS / 1000);
            status_set(SANDY_ST_NO_WIFI);
            vTaskDelay(pdMS_TO_TICKS(1500));   // let the face and the log land
            esp_ota_mark_app_invalid_rollback_and_reboot();
            // Only reached if there is no previous image to go back to — the
            // very first flash of a new board. Nothing to do but carry on.
            ESP_LOGW(TAG, "no previous image to roll back to — staying put");
            vTaskDelete(NULL);
            return;
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
#endif  // ENABLE_WIFI && ENABLE_REMOTE

void ota_start_health_watch(void) {
    const esp_partition_t *p = esp_ota_get_running_partition();
    esp_ota_img_states_t st;

    if (esp_ota_get_state_partition(p, &st) != ESP_OK) {
        s_confirmed = true;   // can't tell; assume fine rather than roll back
        return;
    }
    if (st != ESP_OTA_IMG_PENDING_VERIFY) {
        // An ordinary boot of an already-confirmed image, a wired flash (which
        // writes the app directly and leaves nothing pending), or a build with
        // rollback off. Nothing is watching, nothing to prove.
        //
        // Logged rather than returning in silence: "did rollback arm?" is a
        // question worth being able to answer from a boot log, and the answer
        // after a cable flash is legitimately "not yet — it arms on the first
        // over-the-air update".
        s_confirmed = true;
        ESP_LOGI(TAG, "image state %d — nothing pending, rollback idle", (int)st);
        return;
    }

#if !ENABLE_WIFI || !ENABLE_REMOTE
    // A build with no network or no update server can never prove it is
    // reachable, so waiting for that would roll every image back forever.
    // Confirm straight away: rollback protects the remote-flash path, and this
    // build does not have one.
    ESP_LOGW(TAG, "no remote update path in this build — confirming image now");
    if (esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) s_confirmed = true;
    return;
#else
    ESP_LOGW(TAG, "first boot of a new image — proving it can still be reached");
    xTaskCreate(_health_task, "ota_health", 3072, NULL, 3, NULL);
#endif
}

void ota_trigger(const char *url) {
    if (!url || url[0] == '\0') {
        ESP_LOGE(TAG, "empty URL");
        return;
    }
    ESP_LOGI(TAG, "starting OTA from %s", url);
    esp_http_client_config_t http = {
        .url                        = url,
        .skip_cert_common_name_check = true,   // ⛏️ add cert for production
    };
    esp_https_ota_config_t ota = { .http_config = &http };
    esp_err_t err = esp_https_ota(&ota);
    if (err == ESP_OK) {
        ESP_LOGI(TAG, "OTA success — restarting");
        esp_restart();
    } else {
        ESP_LOGE(TAG, "OTA failed: %s", esp_err_to_name(err));
    }
}
