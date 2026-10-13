#include "sandy_reach.h"
#include "sandy_identity.h"
#include "sandy_net_busy.h"
#include "sandy_wifi.h"
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#include "esp_crt_bundle.h"
#include "esp_http_client.h"
#include "esp_log.h"
#include "esp_timer.h"

static const char *TAG = "reach";

#define REACH_TIMEOUT_MS 8000

static atomic_llong s_last_ms;

void reach_mark(void) {
    const long long now = esp_timer_get_time() / 1000;
    atomic_store(&s_last_ms, now ? now : 1);
}

int64_t reach_last_ms(void) { return atomic_load(&s_last_ms); }

bool reach_api_base(char *out, size_t cap) {
    const char *u = identity()->voice_uri;
    const char *host = strstr(u, "://");
    if (!host) return false;
    host += 3;
    const char *slash = strchr(host, '/');
    int hlen = slash ? (int)(slash - host) : (int)strlen(host);
    if (hlen <= 0) return false;
    int n = snprintf(out, cap, "https://%.*s", hlen, host);
    return n > 0 && n < (int)cap;
}

// Any HTTP answer counts, a 503 too: it came from the server, through TLS checked against its
// real certificate, which a sign-in page cannot fake.
reach_t reach_probe(void) {
    if (!wifi_sandy_is_connected()) return REACH_FAIL;
    char base[96], url[128];
    if (!reach_api_base(base, sizeof(base))) return REACH_UNSET;
    // One TLS session at a time (sandy_net_busy.h).
    if (!net_claim(NET_OWNER_REACH)) return REACH_BUSY;
    snprintf(url, sizeof(url), "%s/health", base);
    esp_http_client_config_t cfg = {
        .url               = url,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .timeout_ms        = REACH_TIMEOUT_MS,
        .buffer_size       = 1024,
    };
    reach_t r = REACH_FAIL;
    esp_http_client_handle_t c = esp_http_client_init(&cfg);
    if (c) {
        if (esp_http_client_open(c, 0) == ESP_OK &&
            esp_http_client_fetch_headers(c) >= 0 &&
            esp_http_client_get_status_code(c) > 0) {
            r = REACH_OK;
        }
        esp_http_client_cleanup(c);
    }
    net_release(NET_OWNER_REACH);
    if (r == REACH_OK) reach_mark();
    else ESP_LOGW(TAG, "the server did not answer from this network");
    return r;
}
