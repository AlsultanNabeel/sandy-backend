#include "sandy_ota.h"
#include "sandy_wifi.h"
#include "sandy_status.h"
#include "config.h"

#include "secrets.h"
#include "sandy_voice.h"

#include <stdlib.h>
#include <string.h>
#include <strings.h>

#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_ota_ops.h"
#include "mbedtls/pk.h"
#include "mbedtls/sha256.h"
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

#if ENABLE_WIFI
static void _health_task(void *arg) {
    (void)arg;
    const int64_t start = esp_timer_get_time() / 1000;

    for (;;) {
        if (wifi_sandy_is_connected()) {
            // Rescuable: back on the network, so it can fetch the next
            // release. Confirm, and the bootloader stops watching.
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
#endif  // ENABLE_WIFI

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

#if !ENABLE_WIFI
    // A build with no network can never prove it is reachable, so waiting for
    // that would roll every image back forever. Confirm straight away.
    ESP_LOGW(TAG, "no network in this build — confirming image now");
    if (esp_ota_mark_app_valid_cancel_rollback() == ESP_OK) s_confirmed = true;
    return;
#else
    ESP_LOGW(TAG, "first boot of a new image — proving it can still be reached");
    xTaskCreate(_health_task, "ota_health", 3072, NULL, 3, NULL);
#endif
}

// ── Pulling signed releases from the server ─────────────────────────────────
//
// A sold robot sits behind somebody else's router: nothing can reach it, so it
// asks. On boot (after a minute) and every few hours it fetches
// /api/firmware/manifest; when a newer release is listed it
//   1. checks the manifest's ECDSA P-256 signature against the public key built
//      into this image (fw_pubkey.pem) — the server cannot forge that;
//   2. streams the image into the idle OTA slot, hashing as it goes;
//   3. refuses it unless the size and SHA-256 match what was signed;
//   4. switches partitions and restarts. The health watch above rolls back an
//      image that cannot get back on the network.
// The signed message is "sandy-fw|<version>|<size>|<sha256>"
// (the string scripts/publish_firmware.py signs). Never a downgrade.

extern const char fw_pubkey_pem_start[] asm("_binary_fw_pubkey_pem_start");
extern const char fw_pubkey_pem_end[]   asm("_binary_fw_pubkey_pem_end");

#define OTA_FIRST_CHECK_MS   (60 * 1000)
#define OTA_PERIOD_MS        (6LL * 60 * 60 * 1000)
#define OTA_MANIFEST_MAX     1024
#define OTA_BUF              4096

static esp_timer_handle_t s_ota_timer;
static volatile bool      s_ota_running;

// "https://host" from the voice URI "wss://host/voice".
static bool api_base(char *out, size_t cap) {
    const char *u = SANDY_VOICE_WS_URI;
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

// -1 / 0 / 1 like strcmp, numerically per dotted part ("0.10" > "0.9").
// Anything that is not a digit or a dot ends the comparison — it can only
// stall, never loop.
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
    mbedtls_sha256((const unsigned char *)msg, n, hash, 0);

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

static void ota_check_once(void) {
    char base[96], url[256];
    if (!api_base(base, sizeof(base))) return;
    snprintf(url, sizeof(url), "%s/api/firmware/manifest?device_id=%s&v=%s",
             base, SANDY_DEVICE_ID, SANDY_FW_VERSION);

    esp_http_client_handle_t c = http_open(url);
    if (!c) { ESP_LOGW(TAG, "update check: server not reachable"); return; }
    esp_http_client_fetch_headers(c);
    int status = esp_http_client_get_status_code(c);
    if (status == 204) {
        esp_http_client_cleanup(c);
        ESP_LOGI(TAG, "update check: %s is current", SANDY_FW_VERSION);
        return;
    }
    char *js = calloc(1, OTA_MANIFEST_MAX + 1);
    int got = js ? esp_http_client_read_response(c, js, OTA_MANIFEST_MAX) : -1;
    esp_http_client_cleanup(c);
    if (status != 200 || got <= 0) {
        ESP_LOGW(TAG, "update check: HTTP %d", status);
        free(js);
        return;
    }

    char version[24], sha[65], sig[161], path[96];
    long size = json_num(js, "size");
    bool ok = json_str(js, "version", version, sizeof(version)) &&
              json_str(js, "sha256", sha, sizeof(sha)) &&
              json_str(js, "signature", sig, sizeof(sig)) &&
              json_str(js, "url", path, sizeof(path)) && size > 0;
    free(js);
    if (!ok) { ESP_LOGW(TAG, "update check: unreadable manifest"); return; }
    if (version_cmp(version, SANDY_FW_VERSION) <= 0) {
        ESP_LOGI(TAG, "update check: %s offered, not newer than %s", version, SANDY_FW_VERSION);
        return;
    }
    if (!signature_ok(version, size, sha, sig)) {
        ESP_LOGE(TAG, "update %s: BAD SIGNATURE — refused", version);
        return;
    }

    const esp_partition_t *slot = esp_ota_get_next_update_partition(NULL);
    if (!slot || size > (long)slot->size) {
        ESP_LOGE(TAG, "update %s: does not fit (%ld bytes)", version, size);
        return;
    }
    ESP_LOGW(TAG, "update %s: signed release, downloading %ld bytes", version, size);

    snprintf(url, sizeof(url), "%s%s", base, path);
    c = http_open(url);
    if (!c) { ESP_LOGW(TAG, "update %s: download failed to start", version); return; }
    esp_http_client_fetch_headers(c);
    if (esp_http_client_get_status_code(c) != 200) {
        ESP_LOGW(TAG, "update %s: HTTP %d", version, esp_http_client_get_status_code(c));
        esp_http_client_cleanup(c);
        return;
    }

    esp_ota_handle_t h;
    if (esp_ota_begin(slot, size, &h) != ESP_OK) {
        esp_http_client_cleanup(c);
        return;
    }
    unsigned char *buf = malloc(OTA_BUF);
    mbedtls_sha256_context sh;
    mbedtls_sha256_init(&sh);
    mbedtls_sha256_starts(&sh, 0);
    long total = 0;
    bool fail = buf == NULL;
    while (!fail && total < size) {
        int n = esp_http_client_read(c, (char *)buf, OTA_BUF);
        if (n <= 0) { fail = true; break; }
        if (total + n > size) { fail = true; break; }   // more than was signed
        mbedtls_sha256_update(&sh, buf, n);
        if (esp_ota_write(h, buf, n) != ESP_OK) fail = true;
        total += n;
    }
    esp_http_client_cleanup(c);
    free(buf);

    unsigned char digest[32];
    char digest_hex[65];
    mbedtls_sha256_finish(&sh, digest);
    mbedtls_sha256_free(&sh);
    for (int i = 0; i < 32; i++) snprintf(digest_hex + 2 * i, 3, "%02x", digest[i]);

    if (fail || total != size || strcasecmp(digest_hex, sha) != 0) {
        ESP_LOGE(TAG, "update %s: download did not match what was signed — discarded", version);
        esp_ota_abort(h);
        return;
    }
    if (esp_ota_end(h) != ESP_OK || esp_ota_set_boot_partition(slot) != ESP_OK) {
        ESP_LOGE(TAG, "update %s: image rejected by the bootloader check", version);
        return;
    }
    ESP_LOGW(TAG, "update %s installed — restarting", version);
    vTaskDelay(pdMS_TO_TICKS(1000));
    esp_restart();
}

static void ota_check_task(void *arg) {
    (void)arg;
    if (wifi_sandy_is_connected() && !voice_is_connected()) {
        ota_check_once();
    } else {
        ESP_LOGI(TAG, "update check skipped (offline or in a call)");
    }
    s_ota_running = false;
    vTaskDelete(NULL);
}

static void spawn_check(void) {
    if (s_ota_running) return;
    s_ota_running = true;
    // Internal RAM on purpose: a task stack in PSRAM is unreachable while
    // esp_ota_write has the flash cache off. TLS buffers go to PSRAM
    // (CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC).
    if (xTaskCreate(ota_check_task, "ota_check", 6144, NULL, 2, NULL) != pdPASS) {
        s_ota_running = false;
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
