#include "sandy_identity.h"

#include <stdio.h>
#include <string.h>

#include "esp_log.h"
#include "nvs.h"
#include "nvs_flash.h"

// The retail build (the one published over the air) never sees the real
// secrets: it compiles the example file, whose values are all placeholders.
#if SANDY_RETAIL
#include "secrets.example.h"
#else
#include "secrets.h"
#endif

static const char *TAG = "identity";

#define ID_NS          "sandyid"      // main NVS: what earlier boots saved
#define FACTORY_PART   "fctry"        // per-unit partition from production
#define FACTORY_NS     "sandy_id"

static sandy_identity_t s_id;

static bool is_placeholder(const char *v) {
    return v == NULL || *v == '\0' || strncmp(v, "YOUR_", 5) == 0 ||
           strstr(v, "XXXX") != NULL || strstr(v, "YOUR_") != NULL;
}

// One field: compiled (saved to NVS when real) → factory → saved.
static void field(nvs_handle_t saved, bool have_saved, nvs_handle_t factory,
                  bool have_factory, const char *key, const char *compiled,
                  char *out, size_t cap) {
    out[0] = '\0';
    if (!is_placeholder(compiled)) {
        snprintf(out, cap, "%s", compiled);
        if (have_saved) {
            char cur[160] = {0};
            size_t len = sizeof(cur);
            if (nvs_get_str(saved, key, cur, &len) != ESP_OK || strcmp(cur, compiled) != 0) {
                if (nvs_set_str(saved, key, compiled) != ESP_OK) {
                    ESP_LOGW(TAG, "could not save %s", key);
                }
            }
        }
        return;
    }
    size_t len = cap;
    if (have_factory && nvs_get_str(factory, key, out, &len) == ESP_OK && out[0]) return;
    len = cap;
    if (have_saved && nvs_get_str(saved, key, out, &len) == ESP_OK) return;
    out[0] = '\0';
}

static void derive_node_id(const char *code, char *out, size_t cap) {
    size_t j = 0;
    for (size_t i = 0; code[i] && j + 1 < cap; i++) {
        char c = code[i];
        if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
        if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) out[j++] = c;
    }
    out[j] = '\0';
}

esp_err_t identity_init(void) {
    nvs_handle_t saved = 0, factory = 0;
    bool have_saved = nvs_open(ID_NS, NVS_READWRITE, &saved) == ESP_OK;

    // The factory partition is optional: boards flashed before it existed, and
    // developer boards, simply do not have one.
    bool have_factory = false;
    if (nvs_flash_init_partition(FACTORY_PART) == ESP_OK) {
        have_factory = nvs_open_from_partition(FACTORY_PART, FACTORY_NS, NVS_READONLY,
                                               &factory) == ESP_OK;
    }

#define F(key, macro, dst) field(saved, have_saved, factory, have_factory, key, macro, \
                                 s_id.dst, sizeof(s_id.dst))
    F("pair",  SANDY_PAIR_CODE,    pair_code);
    F("dev",   SANDY_DEVICE_ID,    device_id);
    F("mqtt",  MQTT_BROKER_URI,    mqtt_uri);
    F("mu",    MQTT_USER,          mqtt_user);
    F("mp",    MQTT_PASS,          mqtt_pass);
    F("voice", SANDY_VOICE_WS_URI, voice_uri);
    F("hmac",  SANDY_WS_HMAC_KEY,  hmac_key);
    F("ws",    WIFI_SSID,          wifi_ssid);
    F("wp",    WIFI_PASS,          wifi_pass);
#undef F

    if (have_saved) {
        if (nvs_commit(saved) != ESP_OK) ESP_LOGW(TAG, "could not commit the identity");
        nvs_close(saved);
    }
    if (have_factory) nvs_close(factory);

    derive_node_id(s_id.pair_code, s_id.node_id, sizeof(s_id.node_id));
    // The voice socket identifies the robot by the same id as its topics. A
    // separate value that drifted (a model name, a typo) made every session
    // anonymous — so when none is given, it *is* the node id.
    if (!s_id.device_id[0]) snprintf(s_id.device_id, sizeof(s_id.device_id), "%s", s_id.node_id);
    if (strcmp(s_id.device_id, s_id.node_id) != 0) {
        ESP_LOGW(TAG, "device id %s differs from node id %s — the voice link will not "
                      "find this robot's owner", s_id.device_id, s_id.node_id);
    }

    if (identity_complete()) {
        ESP_LOGI(TAG, "node %s (%s)", s_id.node_id,
                 have_factory ? "factory identity" : "saved identity");
    } else {
        ESP_LOGE(TAG, "incomplete identity:%s%s%s — flash once by cable with a real "
                      "secrets.h, or provision the factory partition",
                 s_id.node_id[0] ? "" : " no pairing code",
                 s_id.mqtt_uri[0] ? "" : " no broker",
                 s_id.voice_uri[0] ? "" : " no voice server");
    }
    return ESP_OK;
}

esp_err_t identity_save(void) {
    nvs_handle_t h;
    esp_err_t e = nvs_open(ID_NS, NVS_READWRITE, &h);
    if (e != ESP_OK) return e;
    // The Wi-Fi is the owner's, not the robot's: a reset forgets it.
    const struct { const char *key; const char *val; } rows[] = {
        {"pair", s_id.pair_code}, {"dev", s_id.device_id}, {"mqtt", s_id.mqtt_uri},
        {"mu", s_id.mqtt_user},   {"mp", s_id.mqtt_pass},  {"voice", s_id.voice_uri},
        {"hmac", s_id.hmac_key},
    };
    for (size_t i = 0; e == ESP_OK && i < sizeof(rows) / sizeof(rows[0]); i++) {
        if (rows[i].val[0]) e = nvs_set_str(h, rows[i].key, rows[i].val);
    }
    if (e == ESP_OK) e = nvs_commit(h);
    nvs_close(h);
    return e;
}

const sandy_identity_t *identity(void) { return &s_id; }

bool identity_complete(void) {
    return s_id.node_id[0] && s_id.mqtt_uri[0] && s_id.voice_uri[0];
}
