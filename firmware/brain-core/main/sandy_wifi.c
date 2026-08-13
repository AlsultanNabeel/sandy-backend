#include "sandy_wifi.h"
#include "esp_wifi.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "secrets.h"

static const char *TAG = "wifi";

#define WIFI_CONNECTED_BIT  BIT0

// Paced retry. Reconnecting straight from the disconnect event spins hard when
// the AP is simply gone, and there is no cap any more — a router reboot that
// outlasted the old ten tries left the robot offline until it was power-cycled.
#define WIFI_RETRY_MS       5000

static EventGroupHandle_t s_eg;

static void _handler(void *arg, esp_event_base_t base, int32_t id, void *data) {
    if (base == WIFI_EVENT) {
        if (id == WIFI_EVENT_STA_START) {
            esp_wifi_connect();
        } else if (id == WIFI_EVENT_STA_DISCONNECTED) {
            wifi_event_sta_disconnected_t *ev = (wifi_event_sta_disconnected_t *)data;
            xEventGroupClearBits(s_eg, WIFI_CONNECTED_BIT);
            ESP_LOGW(TAG, "disconnected (reason=%d) — retrying every %dms",
                     ev ? ev->reason : -1, WIFI_RETRY_MS);
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "IP: " IPSTR, IP2STR(&ev->ip_info.ip));
        xEventGroupSetBits(s_eg, WIFI_CONNECTED_BIT);
    }
}

// Retries forever while the link is down. Owning the retry here (instead of in
// the event handler) keeps the pacing in one place and keeps the event task free.
static void _retry_task(void *arg) {
    uint32_t tries = 0;
    for (;;) {
        if (xEventGroupGetBits(s_eg) & WIFI_CONNECTED_BIT) {
            tries = 0;
        } else {
            tries++;
            // First attempt after each drop, then one line a minute: a dead
            // router must not flood the 8KB remote log buffer with retry noise.
            if (tries == 1 || tries % 12 == 0) {
                ESP_LOGI(TAG, "reconnecting (attempt %lu)", (unsigned long)tries);
            }
            esp_wifi_connect();
        }
        vTaskDelay(pdMS_TO_TICKS(WIFI_RETRY_MS));
    }
}

// Report and bail instead of aborting: a Wi-Fi stack that won't come up is no
// reason to lose the face, the wake word and the offline room commands.
#define WIFI_TRY(what, call)                                                   \
    do {                                                                       \
        esp_err_t _e = (call);                                                 \
        if (_e != ESP_OK) {                                                    \
            ESP_LOGE(TAG, "%s: %s", (what), esp_err_to_name(_e));              \
            return _e;                                                         \
        }                                                                      \
    } while (0)

esp_err_t wifi_sandy_start(void) {
    s_eg = xEventGroupCreate();
    if (!s_eg) return ESP_ERR_NO_MEM;

    WIFI_TRY("netif init", esp_netif_init());
    WIFI_TRY("event loop", esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    WIFI_TRY("wifi init", esp_wifi_init(&init_cfg));

    WIFI_TRY("wifi events", esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, _handler, NULL, NULL));
    WIFI_TRY("ip events", esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, _handler, NULL, NULL));

    wifi_config_t wifi_cfg = {
        .sta = {
            .ssid               = WIFI_SSID,
            .password           = WIFI_PASS,
            .threshold.authmode = WIFI_AUTH_WPA2_PSK,
            .pmf_cfg            = { .capable = true, .required = false },
        },
    };
    WIFI_TRY("set mode", esp_wifi_set_mode(WIFI_MODE_STA));
    WIFI_TRY("set config", esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    WIFI_TRY("wifi start", esp_wifi_start());
    // No modem sleep: the default WIFI_PS_MIN_MODEM naps between DTIM beacons,
    // which turns a steady audio stream into late bursts — the #1 source of
    // choppy playback. The robot runs off a supply, so the power cost is fine.
    WIFI_TRY("power save off", esp_wifi_set_ps(WIFI_PS_NONE));

    xTaskCreate(_retry_task, "wifi_retry", 3072, NULL, 3, NULL);

    // Returns as soon as the radio is up — association happens in the
    // background. Boot used to block here until connected, then hand an
    // ESP_FAIL to an ESP_ERROR_CHECK, so a router that was down at power-on
    // meant an endless reboot loop with no face and no wake word. Everything
    // that actually needs the link already waits for it: voice_task polls
    // wifi_sandy_is_connected(), and the MQTT client retries on its own.
    ESP_LOGI(TAG, "radio up — associating with '%s' in the background", WIFI_SSID);
    return ESP_OK;
}
#undef WIFI_TRY

bool wifi_sandy_is_connected(void) {
    if (!s_eg) return false;
    return (xEventGroupGetBits(s_eg) & WIFI_CONNECTED_BIT) != 0;
}
