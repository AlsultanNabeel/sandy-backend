#include "sandy_clock.h"
#include "config.h"
#if ENABLE_WIFI
#include "sandy_wifi.h"
#endif

#include <stdio.h>
#include <time.h>

#include "esp_log.h"
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "esp_timer.h"

static const char *TAG = "clock";

static volatile bool s_refused;
static int64_t s_started_ms;

static int64_t now_ms(void) {
    return esp_timer_get_time() / 1000;
}

static void on_sync(struct timeval *tv) {
    (void)tv;
    s_refused = false;
    ESP_LOGI(TAG, "clock synced");
}

static void start(void) {
    static char gw[16];
    esp_netif_ip_info_t ip;
    esp_netif_t *sta = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (sta && esp_netif_get_ip_info(sta, &ip) == ESP_OK && ip.gw.addr) {
        esp_ip4addr_ntoa(&ip.gw, gw, sizeof(gw));
    } else {
        snprintf(gw, sizeof(gw), "pool.ntp.org");   // no gateway yet: one public server twice
    }
    esp_sntp_config_t cfg = ESP_NETIF_SNTP_DEFAULT_CONFIG_MULTIPLE(4,
        ESP_SNTP_SERVER_LIST(gw, "time.google.com", "time.cloudflare.com", "pool.ntp.org"));
    cfg.sync_cb = on_sync;
    cfg.wait_for_sync = false;
    if (s_started_ms) esp_netif_sntp_deinit();   // a resync: start over, same servers
    if (esp_netif_sntp_init(&cfg) != ESP_OK) {
        ESP_LOGW(TAG, "sntp init failed");
        return;
    }
    s_started_ms = now_ms();
    ESP_LOGI(TAG, "clock: asking %s, then public servers", gw);
}

void clock_poll(void) {
#if ENABLE_WIFI
    if (!s_started_ms && wifi_sandy_is_connected()) start();
#endif
}

bool clock_ok(void) {
    return time(NULL) > 1700000000 && !s_refused;   // ~2023-11
}

void clock_refuse(void) { s_refused = true; }
bool clock_refused(void) { return s_refused; }
void clock_resync(void) { start(); }
int64_t clock_started_ms(void) { return s_started_ms; }
