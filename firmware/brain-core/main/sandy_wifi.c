#include "sandy_wifi.h"
#include "config.h"
#include "sandy_provision.h"
#include "sandy_status.h"
#include "esp_wifi.h"
#include "nvs.h"
#include "esp_event.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "esp_system.h"   // esp_restart — factory reset
#include "nvs_flash.h"    // nvs_flash_erase — factory reset
#include <stdio.h>
#include <string.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/event_groups.h"
#include "sandy_identity.h"

// WPA2 floor with a password; an empty password means an open network.
static wifi_auth_mode_t auth_threshold(const char *pass) {
    return (pass && pass[0]) ? WIFI_AUTH_WPA2_PSK : WIFI_AUTH_OPEN;
}
static const char *TAG = "wifi";
static char s_ip[16] = "";   // آخر عنوان أخذناه، للنبضة

#define WIFI_CONNECTED_BIT  BIT0

// Paced, uncapped retry: the old ten-try cap left the robot offline after router reboots.
#define WIFI_RETRY_MS       5000
// Back off to this on repeated failures.
#define WIFI_RETRY_MAX_MS   60000
// Consecutive "wrong password" answers before saying so; one could be a busy-router timeout.
#define WIFI_BAD_PASS_AFTER 3

static EventGroupHandle_t s_eg;
static TaskHandle_t       s_retry_task;

// Declared here: the retry task reads it.
static volatile bool s_switching;
static volatile int  s_bad_pass_count;
static volatile bool s_had_ip_this_try;

// A handshake that timed out is a wrong password only when the router is heard well;
// from a weak signal it is just the radio losing frames.
#define WIFI_BAD_PASS_MIN_RSSI  (-70)

// Reasons meaning "the router refused us" rather than "no router" or "too far".
static bool reason_is_bad_password(int r, int rssi) {
    if (r == WIFI_REASON_AUTH_FAIL || r == WIFI_REASON_MIC_FAILURE) return true;
    const bool timed_out = r == WIFI_REASON_4WAY_HANDSHAKE_TIMEOUT ||
                           r == WIFI_REASON_HANDSHAKE_TIMEOUT || r == WIFI_REASON_AUTH_EXPIRE;
    return timed_out && rssi < 0 && rssi >= WIFI_BAD_PASS_MIN_RSSI;   // 0 = not reported
}

bool wifi_sandy_password_rejected(void) { return s_bad_pass_count >= WIFI_BAD_PASS_AFTER; }

static void _handler(void *arg, esp_event_base_t base, int32_t id, void *data) {
    if (base == WIFI_EVENT) {
        if (id == WIFI_EVENT_STA_START) {
            esp_wifi_connect();
        } else if (id == WIFI_EVENT_STA_DISCONNECTED) {
            wifi_event_sta_disconnected_t *ev = (wifi_event_sta_disconnected_t *)data;
            const bool was_up = (xEventGroupGetBits(s_eg) & WIFI_CONNECTED_BIT) != 0;
            xEventGroupClearBits(s_eg, WIFI_CONNECTED_BIT);
            s_ip[0] = '\0';   // no address now; never report the old one
            // Only on the up→down edge: retry at once so a voice call survives the gap.
            if (was_up && s_retry_task) xTaskNotifyGive(s_retry_task);
            const int reason = ev ? ev->reason : -1;
            const int rssi = ev ? ev->rssi : -127;
            const bool refused = reason_is_bad_password(reason, rssi);
            if (refused) {
                if (s_bad_pass_count < 1000) s_bad_pass_count++;
            } else if (reason == WIFI_REASON_NO_AP_FOUND) {
                s_bad_pass_count = 0;   // no router at all is a different answer
            }
            ESP_LOGW(TAG, "disconnected (reason=%d rssi=%d%s)", reason, rssi,
                     refused ? ", password refused" : "");
        }
    } else if (base == IP_EVENT && id == IP_EVENT_STA_GOT_IP) {
        ip_event_got_ip_t *ev = (ip_event_got_ip_t *)data;
        ESP_LOGI(TAG, "IP: " IPSTR, IP2STR(&ev->ip_info.ip));
        // نحفظه للنبضة: العنوان بيتغيّر مع الراوتر.
        snprintf(s_ip, sizeof(s_ip), IPSTR, IP2STR(&ev->ip_info.ip));
        s_bad_pass_count = 0;
        xEventGroupSetBits(s_eg, WIFI_CONNECTED_BIT);
        status_set(SANDY_PART_NET, SANDY_ST_OK);   // Wi-Fi owns its own recovery
    }
}

// Retries forever while down; pacing lives here, off the event task.
static void _retry_task(void *arg) {
    uint32_t tries = 0;
    uint32_t wait_ms = WIFI_RETRY_MS;
    for (;;) {
        if (xEventGroupGetBits(s_eg) & WIFI_CONNECTED_BIT) {
            tries = 0;
            wait_ms = WIFI_RETRY_MS;
        } else if (s_switching) {
            // A credential test owns the radio: reconnecting now would fail it as "wrong password".
            tries = 0;
#if ENABLE_PROVISION
        } else if (provision_is_active()) {
            // In setup mode, still try the saved network every half minute.
            wait_ms = WIFI_RETRY_MS;
            if (++tries % 6 == 0 && wifi_sandy_ssid()[0]) esp_wifi_connect();
#endif
        } else {
            tries++;
            // Log the first try, then once a minute (the remote log buffer is 8 KB).
            if (tries == 1 || tries % 12 == 0) {
                ESP_LOGI(TAG, "reconnecting (attempt %lu, next in %lus)",
                         (unsigned long)tries, (unsigned long)(wait_ms / 1000));
            }
            esp_wifi_connect();
            // 5 s while it might be a blip, then back off.
            if (tries > 6 && wait_ms < WIFI_RETRY_MAX_MS) {
                wait_ms = wait_ms * 2 > WIFI_RETRY_MAX_MS ? WIFI_RETRY_MAX_MS : wait_ms * 2;
            }
        }
        // Woken early by a fresh drop.
        if (ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(wait_ms))) {
            tries = 0;
            wait_ms = WIFI_RETRY_MS;
        }
    }
}

// Report and bail instead of aborting: keep the face and wake word alive.
#define WIFI_TRY(what, call)                                                   \
    do {                                                                       \
        esp_err_t _e = (call);                                                 \
        if (_e != ESP_OK) {                                                    \
            ESP_LOGE(TAG, "%s: %s", (what), esp_err_to_name(_e));              \
            return _e;                                                         \
        }                                                                      \
    } while (0)

// ── بيانات الشبكة ──

#define WIFI_NS   "sandy_wifi"
#define K_SSID    "ssid"
#define K_PASS    "pass"
#define K_TRYING  "trying"

static char s_ssid[33];
static char s_pass[65];

const char *wifi_sandy_ssid(void) { return s_ssid; }

// مسح المصنع — للبيع أو الإهداء: ما لازم تنباع بيانات بيت البائع مع الجهاز.
void wifi_sandy_factory_reset(void) {
    // بنمسح الذاكرة كلها (مش sandy_wifi بس) وبنرجّع الهويّة بس، لأنها للجهاز مش للمالك.
    esp_wifi_restore();   // the driver's own copy (nvs.net80211)
    esp_err_t e = nvs_flash_erase();
    if (e == ESP_OK) e = nvs_flash_init();
    if (e == ESP_OK) e = identity_save();
    ESP_LOGW(TAG, "factory reset — %s", e == ESP_OK ? "everything erased, identity kept"
                                                    : esp_err_to_name(e));
    // تأخير بسيط عشان يوصل الردّ للتطبيق قبل إعادة التشغيل.
    vTaskDelay(pdMS_TO_TICKS(500));
    esp_restart();
}

static void _nvs_get_str(nvs_handle_t h, const char *key, char *out, size_t cap) {
    size_t len = cap;
    if (nvs_get_str(h, key, out, &len) != ESP_OK) out[0] = '\0';
}

static void _load_creds(void) {
    snprintf(s_ssid, sizeof(s_ssid), "%s", identity()->wifi_ssid);
    snprintf(s_pass, sizeof(s_pass), "%s", identity()->wifi_pass);

    nvs_handle_t h;
    if (nvs_open(WIFI_NS, NVS_READWRITE, &h) != ESP_OK) return;

    // حارس الإقلاع: علامة «قيد التجربة» بتنمسح عند كل إقلاع، والشبكة المحفوظة
    // بتنقرا دايمًا لأنها آخر شبكة نجحت.
    uint8_t trying = 0;
    if (nvs_get_u8(h, K_TRYING, &trying) == ESP_OK && trying) {
        ESP_LOGW(TAG, "a network switch was interrupted — back on the last good one");
        nvs_erase_key(h, K_TRYING);
        if (nvs_commit(h) != ESP_OK) ESP_LOGW(TAG, "could not clear the switch marker");
    }
    char ssid[33], pass[65];
    _nvs_get_str(h, K_SSID, ssid, sizeof(ssid));
    _nvs_get_str(h, K_PASS, pass, sizeof(pass));
    if (ssid[0]) {
        snprintf(s_ssid, sizeof(s_ssid), "%s", ssid);
        snprintf(s_pass, sizeof(s_pass), "%s", pass);
        ESP_LOGI(TAG, "using saved network '%s'", s_ssid);
    }
    nvs_close(h);
}

// حقول 802.11 بايتات بطول ثابت بلا صفر بالآخر؛ snprintf كانت تقصّ آخر حرف
// من اسم طوله ٣٢.
static void set_wifi_field(uint8_t *dst, size_t cap, const char *src) {
    size_t n = src ? strlen(src) : 0;
    if (n > cap) n = cap;
    memset(dst, 0, cap);
    if (n) memcpy(dst, src, n);
}

wifi_switch_result_t wifi_sandy_switch(const char *ssid, const char *pass) {
    if (!ssid || !*ssid || strlen(ssid) > 32 || (pass && strlen(pass) > 64)) {
        return WIFI_SWITCH_BAD_ARGS;
    }
    if (s_switching) return WIFI_SWITCH_BUSY;
    s_switching = true;

    char old_ssid[33], old_pass[65];
    snprintf(old_ssid, sizeof(old_ssid), "%s", s_ssid);
    snprintf(old_pass, sizeof(old_pass), "%s", s_pass);

    // «قيد التجربة» بينكتب قبل ما نلمس الراديو.
    nvs_handle_t h;
    if (nvs_open(WIFI_NS, NVS_READWRITE, &h) != ESP_OK ||
        nvs_set_u8(h, K_TRYING, 1) != ESP_OK || nvs_commit(h) != ESP_OK) {
        // Without the marker, a power cut could boot into an unproven network.
        ESP_LOGE(TAG, "could not mark the trial — switch refused");
        s_switching = false;
        return WIFI_SWITCH_FAILED;
    }
    nvs_close(h);

    ESP_LOGW(TAG, "trying network '%s' (%d s, then back to '%s')",
             ssid, WIFI_TRY_WINDOW_MS / 1000, old_ssid);

    wifi_config_t cfg = { 0 };
    set_wifi_field(cfg.sta.ssid, sizeof(cfg.sta.ssid), ssid);
    set_wifi_field(cfg.sta.password, sizeof(cfg.sta.password), pass ? pass : "");
    cfg.sta.threshold.authmode = auth_threshold(pass);
    cfg.sta.pmf_cfg.capable = true;

    // Clear the old link's bits first, or the wait below sees them and saves an untried password.
    xEventGroupClearBits(s_eg, WIFI_CONNECTED_BIT);
    s_ip[0] = '\0';
    s_bad_pass_count = 0;
    esp_wifi_disconnect();
    esp_wifi_set_config(WIFI_IF_STA, &cfg);
    esp_wifi_connect();

    // بننتظر عنوان مش «اتصال»: بلا عنوان ما في وصول للخادم.
    const int step_ms = 250;
    int waited = 0;
    bool ok = false;
    while (waited < WIFI_TRY_WINDOW_MS) {
        vTaskDelay(pdMS_TO_TICKS(step_ms));
        waited += step_ms;
        if (wifi_sandy_is_connected() && wifi_sandy_ip()[0]) { ok = true; break; }
        if (wifi_sandy_password_rejected()) break;   // no point waiting it out
    }
    const bool bad_pass = !ok && wifi_sandy_password_rejected();

    if (nvs_open(WIFI_NS, NVS_READWRITE, &h) == ESP_OK) {
        esp_err_t e = ESP_OK;
        if (ok) {
            e = nvs_set_str(h, K_SSID, ssid);
            if (e == ESP_OK) e = nvs_set_str(h, K_PASS, pass ? pass : "");
        }
        nvs_erase_key(h, K_TRYING);
        if (e == ESP_OK) e = nvs_commit(h);
        nvs_close(h);
        if (e != ESP_OK) ESP_LOGE(TAG, "the new network works but was not saved: %s",
                                  esp_err_to_name(e));
    }

    if (ok) {
        snprintf(s_ssid, sizeof(s_ssid), "%s", ssid);
        snprintf(s_pass, sizeof(s_pass), "%s", pass ? pass : "");
        ESP_LOGI(TAG, "switched to '%s' — saved", s_ssid);
        s_switching = false;
        return WIFI_SWITCH_OK;
    }

    ESP_LOGW(TAG, "'%s' %s — going back to '%s'", ssid,
             bad_pass ? "refused the password" : "did not come up", old_ssid);
    xEventGroupClearBits(s_eg, WIFI_CONNECTED_BIT);
    s_ip[0] = '\0';
    s_bad_pass_count = 0;
    wifi_config_t back = { 0 };
    set_wifi_field(back.sta.ssid, sizeof(back.sta.ssid), old_ssid);
    set_wifi_field(back.sta.password, sizeof(back.sta.password), old_pass);
    back.sta.threshold.authmode = auth_threshold(old_pass);
    back.sta.pmf_cfg.capable = true;
    esp_wifi_disconnect();
    esp_wifi_set_config(WIFI_IF_STA, &back);
    esp_wifi_connect();
    s_switching = false;
    return bad_pass ? WIFI_SWITCH_BAD_PASSWORD : WIFI_SWITCH_FAILED;
}

esp_err_t wifi_sandy_start(void) {
    s_eg = xEventGroupCreate();
    if (!s_eg) return ESP_ERR_NO_MEM;

    WIFI_TRY("netif init", esp_netif_init());
    WIFI_TRY("event loop", esp_event_loop_create_default());
    esp_netif_create_default_wifi_sta();

    wifi_init_config_t init_cfg = WIFI_INIT_CONFIG_DEFAULT();
    WIFI_TRY("wifi init", esp_wifi_init(&init_cfg));
    // RAM storage: our `sandy_wifi` copy is the only one; a driver copy would survive a reset.
    WIFI_TRY("wifi storage", esp_wifi_set_storage(WIFI_STORAGE_RAM));

    WIFI_TRY("wifi events", esp_event_handler_instance_register(
        WIFI_EVENT, ESP_EVENT_ANY_ID, _handler, NULL, NULL));
    WIFI_TRY("ip events", esp_event_handler_instance_register(
        IP_EVENT, IP_EVENT_STA_GOT_IP, _handler, NULL, NULL));

    // المحفوظة تغلب المكتوبة بالكود؛ المكتوبة بتضل خطّ رجعة.
    _load_creds();
    wifi_config_t wifi_cfg = { 0 };
    set_wifi_field(wifi_cfg.sta.ssid, sizeof(wifi_cfg.sta.ssid), s_ssid);
    set_wifi_field(wifi_cfg.sta.password, sizeof(wifi_cfg.sta.password), s_pass);
    wifi_cfg.sta.threshold.authmode = auth_threshold(s_pass);
    wifi_cfg.sta.pmf_cfg.capable = true;
    wifi_cfg.sta.pmf_cfg.required = false;
    WIFI_TRY("set mode", esp_wifi_set_mode(WIFI_MODE_STA));
    WIFI_TRY("set config", esp_wifi_set_config(WIFI_IF_STA, &wifi_cfg));
    WIFI_TRY("wifi start", esp_wifi_start());
    // No modem sleep: DTIM naps turn the audio stream into bursts and choppy playback.
    WIFI_TRY("power save off", esp_wifi_set_ps(WIFI_PS_NONE));

    xTaskCreate(_retry_task, "wifi_retry", 3072, NULL, 3, &s_retry_task);

    // Non-blocking: association happens in the background; voice and MQTT wait for it.
    ESP_LOGI(TAG, "radio up — associating with '%s' in the background", s_ssid);
    return ESP_OK;
}
#undef WIFI_TRY

const char *wifi_sandy_ip(void) {
    return s_ip;
}

int wifi_sandy_rssi(void) {
    if (!wifi_sandy_is_connected()) return 0;
    wifi_ap_record_t ap;
    if (esp_wifi_sta_get_ap_info(&ap) != ESP_OK) return 0;
    return ap.rssi;
}

bool wifi_sandy_is_connected(void) {
    if (!s_eg) return false;
    return (xEventGroupGetBits(s_eg) & WIFI_CONNECTED_BIT) != 0;
}
