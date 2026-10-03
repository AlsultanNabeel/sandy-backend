#include "sandy_ota.h"
#include "sandy_wifi.h"
#include "sandy_status.h"
#include "config.h"

#include "sandy_identity.h"
#include "sandy_voice.h"
#include "sandy_net_busy.h"

#include <stdatomic.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "nvs.h"

#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_ota_ops.h"
#include "mbedtls/pk.h"
// Generic md API: IDF 6's mbedtls 4 dropped the legacy `mbedtls/sha256.h`.
#include "mbedtls/md.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "ota";

// Deadline for Wi-Fi to associate before rollback.
#define OTA_HEALTH_TIMEOUT_MS  120000
// Wi-Fi must stay up this long (images that crash the stack later).
#define OTA_HEALTH_STABLE_MS   60000
// Then the update server must answer: an image with broken TLS/HTTP can never update again.
// An internet outage costs one retry, not the release (OTA_BAD_MAX_TRIES).
#define OTA_HEALTH_SERVER_MS   (10 * 60 * 1000)
// Trials a version may fail before it is no longer offered (one outage shouldn't bury it).
#define OTA_BAD_MAX_TRIES      2
#define OTA_NVS_NS             "sandyota"

static volatile bool s_confirmed;

// ── Remembering what was tried ──
// The version is saved as "trying" before restart; booting anything else means the
// bootloader rolled back, so it failed. Stops re-downloading a bad release forever.

static void ota_nvs_note_trying(const char *version) {
    nvs_handle_t h;
    if (nvs_open(OTA_NVS_NS, NVS_READWRITE, &h) != ESP_OK) return;
    if (nvs_set_str(h, "trying", version) != ESP_OK || nvs_commit(h) != ESP_OK) {
        ESP_LOGW(TAG, "could not note the version being tried");
    }
    nvs_close(h);
}

static void ota_nvs_check_last_try(void) {
    nvs_handle_t h;
    if (nvs_open(OTA_NVS_NS, NVS_READWRITE, &h) != ESP_OK) return;
    char trying[24] = {0};
    size_t len = sizeof(trying);
    if (nvs_get_str(h, "trying", trying, &len) == ESP_OK && trying[0]) {
        if (strcmp(trying, SANDY_FW_VERSION) != 0) {
            char bad[24] = {0};
            size_t blen = sizeof(bad);
            uint8_t tries = 0;
            if (nvs_get_str(h, "bad", bad, &blen) == ESP_OK && strcmp(bad, trying) == 0) {
                nvs_get_u8(h, "bad_n", &tries);
            }
            tries++;
            nvs_set_str(h, "bad", trying);
            nvs_set_u8(h, "bad_n", tries);
            ESP_LOGE(TAG, "update %s failed its trial (%u) — back on %s",
                     trying, (unsigned)tries, SANDY_FW_VERSION);
        }
        nvs_erase_key(h, "trying");
        if (nvs_commit(h) != ESP_OK) ESP_LOGW(TAG, "could not record the trial");
    }
    nvs_close(h);
}

static bool ota_version_is_bad(const char *version) {
    nvs_handle_t h;
    if (nvs_open(OTA_NVS_NS, NVS_READONLY, &h) != ESP_OK) return false;
    char bad[24] = {0};
    size_t len = sizeof(bad);
    uint8_t tries = 0;
    bool is_bad = nvs_get_str(h, "bad", bad, &len) == ESP_OK &&
                  strcmp(bad, version) == 0 &&
                  nvs_get_u8(h, "bad_n", &tries) == ESP_OK && tries >= OTA_BAD_MAX_TRIES;
    nvs_close(h);
    return is_bad;
}

static bool ota_server_answers(void);

esp_err_t ota_init(void) {
    const esp_partition_t *p = esp_ota_get_running_partition();
    ESP_LOGI(TAG, "running: %s @ 0x%lx", p->label, p->address);
    ota_nvs_check_last_try();
    return ESP_OK;
}

#if ENABLE_WIFI
static void _roll_back(const char *why) {
    ESP_LOGE(TAG, "%s — rolling back to the previous image", why);
    vTaskDelay(pdMS_TO_TICKS(1500));   // let the face and the log land
    esp_ota_mark_app_invalid_rollback_and_reboot();
    // No previous image (first flash): carry on.
    ESP_LOGW(TAG, "no previous image to roll back to — staying put");
}

// Trial: Wi-Fi up, stable for a minute, then the update server answers; each step has a deadline.
static void _health_task(void *arg) {
    (void)arg;
    const int64_t start = esp_timer_get_time() / 1000;
    int64_t up_since = 0;
    bool ever_up = false;

    for (;;) {
        const int64_t now = esp_timer_get_time() / 1000;
        if (!wifi_sandy_is_connected()) {
            up_since = 0;
            if (!ever_up && now - start > OTA_HEALTH_TIMEOUT_MS) {
                status_set(SANDY_PART_NET, SANDY_ST_NO_WIFI);
                _roll_back("no network in two minutes");
                break;
            }
        } else {
            if (!up_since) up_since = now;
            ever_up = true;
            if (now - up_since >= OTA_HEALTH_STABLE_MS) {
                if (ota_server_answers()) {
                    esp_err_t e = esp_ota_mark_app_valid_cancel_rollback();
                    if (e == ESP_OK) {
                        s_confirmed = true;
                        ESP_LOGI(TAG, "image confirmed — rollback cancelled");
                    } else {
                        ESP_LOGW(TAG, "could not confirm image: %s", esp_err_to_name(e));
                    }
                    break;
                }
                vTaskDelay(pdMS_TO_TICKS(15000));   // one TLS handshake per try
            }
        }
        if (now - start > OTA_HEALTH_TIMEOUT_MS + OTA_HEALTH_STABLE_MS + OTA_HEALTH_SERVER_MS) {
            _roll_back(ever_up ? "the network never held and the server never answered"
                               : "no network");
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
    vTaskDelete(NULL);
}
#endif  // ENABLE_WIFI

void ota_start_health_watch(void) {
    const esp_partition_t *p = esp_ota_get_running_partition();
    esp_ota_img_states_t st;

    if (esp_ota_get_state_partition(p, &st) != ESP_OK) {
        s_confirmed = true;   // can't tell; assume fine
        return;
    }
    if (st != ESP_OTA_IMG_PENDING_VERIFY) {
        // Nothing pending: confirmed image, wired flash, or rollback off.
        // Rollback arms on the first OTA update, not after a cable flash.
        s_confirmed = true;
        ESP_LOGI(TAG, "image state %d — nothing pending, rollback idle", (int)st);
        return;
    }

#if !ENABLE_WIFI
    // No network in this build: waiting would roll back forever.
    ESP_LOGW(TAG, "no network in this build — confirming image now");
    if (esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) s_confirmed = true;
    return;
#else
    ESP_LOGW(TAG, "first boot of a new image — proving it can still be reached");
    // Opens HTTPS, so same stack as an update check.
    if (xTaskCreate(_health_task, "ota_health", 6144, NULL, 3, NULL) != pdPASS) {
        ESP_LOGE(TAG, "no memory for the trial — confirming rather than rolling back blind");
        if (esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) s_confirmed = true;
    }
#endif
}

// ── Pulling signed releases from the server ──
// On boot (+1 min) and every few hours, fetch /api/firmware/manifest; for a newer release:
//   1. verify its ECDSA P-256 signature with fw_pubkey.pem;
//   2. stream the image into the idle slot, hashing;
//   3. refuse unless size and SHA-256 match the signed values;
//   4. switch and restart (the health watch rolls back unreachable images).
// Signed message: "sandy-fw|<version>|<size>|<sha256>" (scripts/publish_firmware.py). Never a downgrade.

extern const char fw_pubkey_pem_start[] asm("_binary_fw_pubkey_pem_start");
extern const char fw_pubkey_pem_end[]   asm("_binary_fw_pubkey_pem_end");

#define OTA_FIRST_CHECK_MS   (60 * 1000)
#define OTA_PERIOD_MS        (6LL * 60 * 60 * 1000)
// Retry a skipped check (offline, voice busy) this soon.
#define OTA_RETRY_MS         (5LL * 60 * 1000)
// A failed download or install comes back in minutes, doubling, not after six hours.
#define OTA_FAIL_RETRY_MAX_MS (60LL * 60 * 1000)
// Below this the download crawls and dies halfway: wait for a better moment.
#define OTA_MIN_RSSI         (-80)
// ~400 bytes today; headroom so it never truncates.
#define OTA_MANIFEST_MAX     2048
#define OTA_BUF              4096

static esp_timer_handle_t s_ota_timer;
static int64_t            s_fail_retry_ms;   // 0 = last check did not fail

typedef enum {
    OTA_DONE,      // nothing to do (current, not newer, a known-bad or unsigned release)
    OTA_RETRY,     // try again in minutes: unreachable, cut short, not installed, weak signal
} ota_result_t;

static void ota_retry_in(int64_t ms) {
    if (!s_ota_timer) return;
    esp_timer_stop(s_ota_timer);   // stopping an unarmed timer fails harmlessly
    esp_timer_start_once(s_ota_timer, ms * 1000);
}
// Timer and MQTT tasks both start checks; atomic so only one downloads.
static atomic_bool        s_ota_running;

static bool api_base(char *out, size_t cap) {
    const char *u = identity()->voice_uri;
    const char *host = strstr(u, "://");
    if (!host) return false;
    host += 3;
    const char *slash = strchr(host, '/');
    int hlen = slash ? (int)(slash - host) : (int)strlen(host);
    int n = snprintf(out, cap, "https://%.*s", hlen, host);
    return n > 0 && n < (int)cap;
}

static bool json_str(const char *js, const char *key, char *out, size_t cap) {
    char pat[32];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(js, pat);
    if (!p) return false;
    p = strchr(p + strlen(pat), ':');
    if (!p) return false;
    while (*++p == ' ') {}
    if (*p != '"') return false;
    p++;
    size_t j = 0;
    while (*p && *p != '"' && j + 1 < cap) out[j++] = *p++;
    out[j] = '\0';
    return *p == '"' && j > 0;
}

static long json_num(const char *js, const char *key) {
    char pat[32];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    const char *p = strstr(js, pat);
    if (!p || !(p = strchr(p + strlen(pat), ':'))) return -1;
    return strtol(p + 1, NULL, 10);
}

// strcmp-like, numeric per dotted part ("0.10" > "0.9"). Stops at non-digits.
static int version_cmp(const char *a, const char *b) {
    for (int part = 0; part < 8; part++) {
        char *ea, *eb;
        long x = strtol(a, &ea, 10), y = strtol(b, &eb, 10);
        if (x != y) return x < y ? -1 : 1;
        a = (*ea == '.') ? ea + 1 : ea;
        b = (*eb == '.') ? eb + 1 : eb;
        if ((ea == a && eb == b) || (!*a && !*b)) break;
    }
    return 0;
}

static size_t unhex(const char *hex, unsigned char *out, size_t cap) {
    size_t n = strlen(hex) / 2;
    if (n > cap || strlen(hex) % 2) return 0;
    for (size_t i = 0; i < n; i++) {
        unsigned v;
        if (sscanf(hex + 2 * i, "%2x", &v) != 1) return 0;
        out[i] = (unsigned char)v;
    }
    return n;
}

static bool signature_ok(const char *version, long size, const char *sha_hex,
                         const char *sig_hex) {
    char msg[160];
    int n = snprintf(msg, sizeof(msg), "sandy-fw|%s|%ld|%s", version, size, sha_hex);
    if (n <= 0 || n >= (int)sizeof(msg)) return false;
    unsigned char hash[32], sig[80];
    size_t sig_len = unhex(sig_hex, sig, sizeof(sig));
    if (!sig_len) return false;
    if (mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
                   (const unsigned char *)msg, (size_t)n, hash) != 0) return false;

    mbedtls_pk_context pk;
    mbedtls_pk_init(&pk);
    int r = mbedtls_pk_parse_public_key(&pk, (const unsigned char *)fw_pubkey_pem_start,
                                        fw_pubkey_pem_end - fw_pubkey_pem_start);
    if (r == 0) r = mbedtls_pk_verify(&pk, MBEDTLS_MD_SHA256, hash, sizeof(hash), sig, sig_len);
    mbedtls_pk_free(&pk);
    return r == 0;
}

static esp_http_client_handle_t http_open(const char *url) {
    esp_http_client_config_t cfg = {
        .url               = url,
        .crt_bundle_attach = esp_crt_bundle_attach,   // the server's real certificate
        .timeout_ms        = 15000,
        .buffer_size       = 2048,
    };
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (c && esp_http_client_open(c, 0) != ESP_OK) {
        esp_http_client_cleanup(c);
        return NULL;
    }
    return c;
}

// Any HTTP answer proves TLS, clock and route work.
static bool ota_server_answers(void) {
    if (!net_claim(NET_OWNER_OTA)) return false;   // a call is on; ask later
    char base[96], url[256];
    bool ok = false;
    if (api_base(base, sizeof(base))) {
        snprintf(url, sizeof(url), "%s/api/firmware/manifest?device_id=%s&v=%s",
                 base, identity()->device_id, SANDY_FW_VERSION);
        esp_http_client_handle_t c = http_open(url);
        if (c) {
            esp_http_client_fetch_headers(c);
            int st = esp_http_client_get_status_code(c);
            ok = st == 200 || st == 204;
            esp_http_client_cleanup(c);
        }
    }
    net_release(NET_OWNER_OTA);
    return ok;
}

static ota_result_t ota_check_once(void) {
    char base[96], url[256];
    if (!api_base(base, sizeof(base))) return OTA_DONE;
    snprintf(url, sizeof(url), "%s/api/firmware/manifest?device_id=%s&v=%s",
             base, identity()->device_id, SANDY_FW_VERSION);

    esp_http_client_handle_t c = http_open(url);
    if (!c) { ESP_LOGW(TAG, "update check: server not reachable"); return OTA_RETRY; }
    esp_http_client_fetch_headers(c);
    int status = esp_http_client_get_status_code(c);
    if (status == 204) {
        esp_http_client_cleanup(c);
        ESP_LOGI(TAG, "update check: %s is current", SANDY_FW_VERSION);
        return OTA_DONE;
    }
    char *js = calloc(1, OTA_MANIFEST_MAX + 1);
    int got = js ? esp_http_client_read_response(c, js, OTA_MANIFEST_MAX) : -1;
    esp_http_client_cleanup(c);
    if (status != 200 || got <= 0) {
        ESP_LOGW(TAG, "update check: HTTP %d", status);
        free(js);
        return OTA_RETRY;
    }

    char version[24], sha[65], sig[161], path[96];
    long size = json_num(js, "size");
    bool ok = json_str(js, "version", version, sizeof(version)) &&
              json_str(js, "sha256", sha, sizeof(sha)) &&
              json_str(js, "signature", sig, sizeof(sig)) &&
              json_str(js, "url", path, sizeof(path)) && size > 0;
    free(js);
    if (!ok) { ESP_LOGW(TAG, "update check: unreadable manifest"); return OTA_RETRY; }
    if (version_cmp(version, SANDY_FW_VERSION) <= 0) {
        ESP_LOGI(TAG, "update check: %s offered, not newer than %s", version, SANDY_FW_VERSION);
        return OTA_DONE;
    }
    if (ota_version_is_bad(version)) {
        ESP_LOGW(TAG, "update %s failed its trial %d times — not trying again",
                 version, OTA_BAD_MAX_TRIES);
        return OTA_DONE;
    }
    if (!signature_ok(version, size, sha, sig)) {
        ESP_LOGE(TAG, "update %s: BAD SIGNATURE — refused", version);
        return OTA_DONE;
    }

    const esp_partition_t *slot = esp_ota_get_next_update_partition(NULL);
    if (!slot || size > (long)slot->size) {
        ESP_LOGE(TAG, "update %s: does not fit (%ld bytes)", version, size);
        return OTA_DONE;
    }
    const int rssi = wifi_sandy_rssi();
    if (rssi != 0 && rssi < OTA_MIN_RSSI) {
        ESP_LOGW(TAG, "update %s: signal %d dBm too weak to download — later", version, rssi);
        return OTA_RETRY;
    }
    ESP_LOGW(TAG, "update %s: signed release, downloading %ld bytes", version, size);
    // On her face from here to the restart: pulling the plug now costs the update.
    status_set(SANDY_PART_UPDATE, SANDY_ST_UPDATING);

    snprintf(url, sizeof(url), "%s%s", base, path);
    c = http_open(url);
    if (!c) {
        ESP_LOGW(TAG, "update %s: download failed to start", version);
        status_set(SANDY_PART_UPDATE, SANDY_ST_OK);
        return OTA_RETRY;
    }
    esp_http_client_fetch_headers(c);
    if (esp_http_client_get_status_code(c) != 200) {
        ESP_LOGW(TAG, "update %s: HTTP %d", version, esp_http_client_get_status_code(c));
        esp_http_client_cleanup(c);
        status_set(SANDY_PART_UPDATE, SANDY_ST_OK);
        return OTA_RETRY;
    }

    esp_ota_handle_t h;
    if (esp_ota_begin(slot, size, &h) != ESP_OK) {
        esp_http_client_cleanup(c);
        status_set(SANDY_PART_UPDATE, SANDY_ST_OK);
        return OTA_RETRY;
    }
    unsigned char *buf = malloc(OTA_BUF);
    mbedtls_md_context_t sh;
    mbedtls_md_init(&sh);
    bool fail = buf == NULL ||
                mbedtls_md_setup(&sh, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 0) != 0 ||
                mbedtls_md_starts(&sh) != 0;
    long total = 0;
    while (!fail && total < size) {
        int n = esp_http_client_read(c, (char *)buf, OTA_BUF);
        if (n <= 0) { fail = true; break; }
        if (total + n > size) { fail = true; break; }   // more than was signed
        if (mbedtls_md_update(&sh, buf, (size_t)n) != 0) { fail = true; break; }
        if (esp_ota_write(h, buf, n) != ESP_OK) fail = true;
        total += n;
    }
    esp_http_client_cleanup(c);
    free(buf);

    unsigned char digest[32] = {0};
    char digest_hex[65];
    if (!fail && mbedtls_md_finish(&sh, digest) != 0) fail = true;
    mbedtls_md_free(&sh);
    for (int i = 0; i < 32; i++) snprintf(digest_hex + 2 * i, 3, "%02x", digest[i]);

    if (fail || total != size || strcasecmp(digest_hex, sha) != 0) {
        ESP_LOGE(TAG, "update %s: download did not match what was signed — discarded", version);
        esp_ota_abort(h);
        status_set(SANDY_PART_UPDATE, SANDY_ST_OK);
        return OTA_RETRY;
    }
    if (esp_ota_end(h) != ESP_OK || esp_ota_set_boot_partition(slot) != ESP_OK) {
        ESP_LOGE(TAG, "update %s: image not installed — trying again", version);
        status_set(SANDY_PART_UPDATE, SANDY_ST_OK);
        return OTA_RETRY;
    }
    ota_nvs_note_trying(version);
    ESP_LOGW(TAG, "update %s installed — restarting", version);
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();
    return OTA_DONE;
}

static void ota_check_task(void *arg) {
    (void)arg;
    // Claim the network (taken at the wake word, before the WSS handshake) so OTA
    // never overlaps a voice session. Claim first, check the rest after.
    if (!s_confirmed) {
        // An image on trial installs nothing else.
        ESP_LOGI(TAG, "update check skipped (this image is still on trial)");
        ota_retry_in(OTA_RETRY_MS);
    } else if (wifi_sandy_is_connected() && net_claim(NET_OWNER_OTA)) {
        if (!voice_is_connected()) {
            // esp_restart()s on a successful install.
            if (ota_check_once() == OTA_RETRY) {
                s_fail_retry_ms = s_fail_retry_ms ? s_fail_retry_ms * 2 : OTA_RETRY_MS;
                if (s_fail_retry_ms > OTA_FAIL_RETRY_MAX_MS) s_fail_retry_ms = OTA_FAIL_RETRY_MAX_MS;
                ESP_LOGW(TAG, "update failed — next try in %d min", (int)(s_fail_retry_ms / 60000));
                ota_retry_in(s_fail_retry_ms);
            } else {
                s_fail_retry_ms = 0;
            }
        } else {
            ESP_LOGI(TAG, "update check skipped (in a call)");
        }
        net_release(NET_OWNER_OTA);
    } else {
        ESP_LOGI(TAG, "update check skipped (offline or in a call), retrying in %d min",
                 (int)(OTA_RETRY_MS / 60000));
        ota_retry_in(OTA_RETRY_MS);
    }
    atomic_store(&s_ota_running, false);
    vTaskDelete(NULL);
}

static void spawn_check(void) {
    if (atomic_exchange(&s_ota_running, true)) return;
    // Internal RAM stack: PSRAM is unreachable while esp_ota_write disables the cache.
    if (xTaskCreate(ota_check_task, "ota_check", 6144, NULL, 2, NULL) != pdPASS) {
        atomic_store(&s_ota_running, false);
        ESP_LOGW(TAG, "update check: no memory for the task");
    }
}

static void ota_timer_cb(void *arg) {
    (void)arg;
    spawn_check();
    esp_timer_start_once(s_ota_timer, OTA_PERIOD_MS * 1000);
}

void ota_updates_start(void) {
    const esp_timer_create_args_t a = { .callback = ota_timer_cb, .name = "ota" };
    if (esp_timer_create(&a, &s_ota_timer) == ESP_OK) {
        esp_timer_start_once(s_ota_timer, (int64_t)OTA_FIRST_CHECK_MS * 1000);
    }
}

void ota_check_now(void) {
    spawn_check();
}
