#include "sandy_wifi.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include <stdio.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "secrets.h"

static const char *TAG = "wifi";
static char s_ip[16] = "";   // آخر عنوان أخذناه، للنبضة

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
        // نحفظه عشان النبضة تحمله. العنوان بيوزّعه الراوتر وبيتغيّر، وبلاه
        // إيجاد اللوح ع الشبكة بيصير مسح وتخمين — وهاد بالضبط اللي وقّفنا مرة.
        snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&ev->ip_info.ip));
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

// ── بيانات الشبكة ────────────────────────────────────────────────────────────

#define WIFI_NS   "sandy_wifi"
#define K_SSID    "ssid"
#define K_PASS    "pass"
#define K_TRYING  "trying"

static char s_ssid[33];
static char s_pass[65];

const char *wifi_sandy_ssid(void) { return s_ssid; }

static void _nvs_get_str(nvs_handle_t h, const char *key, char *out, size_t cap) {
    size_t len = cap;
    if (nvs_get_str(h, key, out, &len) != ESP_OK) out[0] = '\0';
}

static void _load_creds(void) {
    snprintf(s_ssid, sizeof(s_ssid), "%s", WIFI_SSID);
    snprintf(s_pass, sizeof(s_pass), "%s", WIFI_PASS);

    nvs_handle_t h;
    if (nvs_open(WIFI_NS, NVS_READWRITE, &h) != ESP_OK) return;

    // حارس الإقلاع.
    //
    // لو انقطعت الكهربا بنص تجربة شبكة جديدة، بتضل «قيد التجربة» محفوظة —
    // ومن غير هالسطر اللوح بيقلع عليها للأبد ع شبكة ما ثبت إنها بتشتغل. مسحها
    // هون بيضمن إنه أي إقلاع بيصير ع شبكة نجحت فعلًا.
    uint8_t trying = 0;
    if (nvs_get_u8(h, K_TRYING, &trying) == ESP_OK && trying) {
        ESP_LOGW(TAG, "a network switch was interrupted — falling back");
        nvs_erase_key(h, K_TRYING);
        nvs_commit(h);
    } else {
        char ssid[33], pass[65];
        _nvs_get_str(h, K_SSID, ssid, sizeof(ssid));
        _nvs_get_str(h, K_PASS, pass, sizeof(pass));
        if (ssid[0]) {
            snprintf(s_ssid, sizeof(s_ssid), "%s", ssid);
            snprintf(s_pass, sizeof(s_pass), "%s", pass);
            ESP_LOGI(TAG, "using saved network '%s'", s_ssid);
        }
    }
    nvs_close(h);
}

static volatile bool s_switching;

wifi_switch_result_t wifi_sandy_switch(const char *ssid, const char *pass) {
    if (!ssid || !*ssid || strlen(ssid) > 32 || (pass && strlen(pass) > 64)) {
        return WIFI_SWITCH_BAD_ARGS;
    }
    if (s_switching) return WIFI_SWITCH_BUSY;
    s_switching = true;

    char old_ssid[33], old_pass[65];
    snprintf(old_ssid, sizeof(old_ssid), "%s", s_ssid);
    snprintf(old_pass, sizeof(old_pass), "%s", s_pass);

    // «قيد التجربة» بينكتب قبل ما نلمس الراديو: إذا وقعت الكهربا من هون لجاي،
    // الإقلاع الجاي بيمسحها وبيرجع ع القديمة.
    nvs_handle_t h;
    if (nvs_open(WIFI_NS, NVS_READWRITE, &h) == ESP_OK) {
        nvs_set_u8(h, K_TRYING, 1);
        nvs_commit(h);
        nvs_close(h);
    }

    ESP_LOGW(TAG, "trying network '%s' (%d s, then back to '%s')",
             ssid, WIFI_TRY_WINDOW_MS / 1000, old_ssid);

    wifi_config_t cfg = { 0 };
    snprintf((char *)cfg.sta.ssid, sizeof(cfg.sta.ssid), "%s", ssid);
    snprintf((char *)cfg.sta.password, sizeof(cfg.sta.password), "%s", pass ? pass : "");
    cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    cfg.sta.pmf_cfg.capable = true;

    esp_wifi_disconnect();
    esp_wifi_set_config(WIFI_IF_STA, &cfg);
    esp_wifi_connect();

    // بننتظر عنوان، مش «اتصال»: الاتصال بيصير قبل ما يجي العنوان، ولوح إله
    // اتصال وبلا عنوان ما بيقدر يوصل الخادم — يعني مقطوع، بس شكله متصل.
    const int step_ms = 250;
    int waited = 0;
    bool ok = false;
    while (waited < WIFI_TRY_WINDOW_MS) {
        vTaskDelay(pdMS_TO_TICKS(step_ms));
        waited += step_ms;
        if (wifi_sandy_is_connected() && wifi_sandy_ip()[0]) { ok = true; break; }
    }

    if (nvs_open(WIFI_NS, NVS_READWRITE, &h) == ESP_OK) {
        if (ok) {
            nvs_set_str(h, K_SSID, ssid);
            nvs_set_str(h, K_PASS, pass ? pass : "");
        }
        nvs_erase_key(h, K_TRYING);
        nvs_commit(h);
        nvs_close(h);
    }

    if (ok) {
        snprintf(s_ssid, sizeof(s_ssid), "%s", ssid);
        snprintf(s_pass, sizeof(s_pass), "%s", pass ? pass : "");
        ESP_LOGI(TAG, "switched to '%s' — saved", s_ssid);
        s_switching = false;
        return WIFI_SWITCH_OK;
    }

    ESP_LOGW(TAG, "'%s' did not come up — going back to '%s'", ssid, old_ssid);
    wifi_config_t back = { 0 };
    snprintf((char *)back.sta.ssid, sizeof(back.sta.ssid), "%s", old_ssid);
    snprintf((char *)back.sta.password, sizeof(back.sta.password), "%s", old_pass);
    back.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    back.sta.pmf_cfg.capable = true;
    esp_wifi_disconnect();
    esp_wifi_set_config(WIFI_IF_STA, &back);
    esp_wifi_connect();
    s_switching = false;
    return WIFI_SWITCH_FAILED;
}

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

    // الشبكة المحفوظة تغلب المكتوبة بالكود.
    //
    // المكتوبة بالكود ضلّت كخطّ رجعة: لوح انحرق ولسا ما حدا غيّر شبكته بيشتغل
    // زي ما كان، ومسح الذاكرة بيرجّعه لنقطة معروفة بدل ما يخلّيه بلا شبكة خالص.
    _load_creds();
    wifi_config_t wifi_cfg = { 0 };
    snprintf((char *)wifi_cfg.sta.ssid, sizeof(wifi_cfg.sta.ssid), "%s", s_ssid);
    snprintf((char *)wifi_cfg.sta.password, sizeof(wifi_cfg.sta.password), "%s", s_pass);
    wifi_cfg.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    wifi_cfg.sta.pmf_cfg.capable = true;
    wifi_cfg.sta.pmf_cfg.required = false;
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
    ESP_LOGI(TAG, "radio up — associating with '%s' in the background", s_ssid);
    return ESP_OK;
}
#undef WIFI_TRY

const char *wifi_sandy_ip(void) {
    return s_ip;
}

bool wifi_sandy_is_connected(void) {
    if (!s_eg) return false;
    return (xEventGroupGetBits(s_eg) & WIFI_CONNECTED_BIT) != 0;
}
