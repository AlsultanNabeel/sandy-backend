// Dev only (ENABLE_REMOTE): OTA upload over HTTP + serial log over TCP.

#include "config.h"
#if ENABLE_REMOTE

#include "sandy_remote.h"
#include <string.h>
#include <stdarg.h>
#include <errno.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/stream_buffer.h"
#include "freertos/semphr.h"
#include "esp_log.h"
#include "esp_http_server.h"
#include "esp_ota_ops.h"
#include "esp_heap_caps.h"
#include "sandy_wifi.h"
#include "sandy_nvs.h"
#include "sandy_echo_probe.h"
#include "config.h"
#include "lwip/sockets.h"

static const char *TAG = "remote";

#ifndef MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
#endif

// ─── Remote serial log (TCP, port 3333) ───
#define LOG_PORT       3333
#define LOG_BUF_BYTES  8192

static StreamBufferHandle_t s_logbuf;
static vprintf_like_t       s_old_vprintf;
// Every task logs, and a stream buffer takes one writer at a time: lines from two tasks
// interleaved or corrupted the buffer. The lock also guards the one shared line buffer,
// which keeps 200 bytes off the stack of whichever small task is logging.
static SemaphoreHandle_t    s_log_lock;

// Tee esp_log to UART and a buffer. Always buffered; when full, new lines drop,
// so boot lines survive until a client connects.
static int log_vprintf(const char *fmt, va_list ap) {
    va_list cp;
    va_copy(cp, ap);
    int r = s_old_vprintf ? s_old_vprintf(fmt, ap) : 0;
    // A line that cannot get the lock at once is lost to the remote log only (UART has it).
    if (s_logbuf && s_log_lock && xSemaphoreTake(s_log_lock, pdMS_TO_TICKS(5)) == pdTRUE) {
        static char line[200];
        int n = vsnprintf(line, sizeof(line), fmt, cp);
        if (n > 0) xStreamBufferSend(s_logbuf, line, MIN(n, (int)sizeof(line) - 1), 0);
        xSemaphoreGive(s_log_lock);
    }
    va_end(cp);
    return r;
}

static void log_server_task(void *arg) {
    int srv = socket(AF_INET, SOCK_STREAM, 0);
    int opt = 1;
    setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    struct sockaddr_in addr = {
        .sin_family      = AF_INET,
        .sin_port        = htons(LOG_PORT),
        .sin_addr.s_addr = htonl(INADDR_ANY),
    };
    bind(srv, (struct sockaddr *)&addr, sizeof(addr));
    listen(srv, 1);

    for (;;) {
        int c = accept(srv, NULL, NULL);
        if (c < 0) { vTaskDelay(pdMS_TO_TICKS(200)); continue; }
        // Keepalive so a vanished client doesn't wedge this single-client server.
        int ka = 1, idle = 5, intvl = 5, cnt = 3;
        setsockopt(c, SOL_SOCKET,  SO_KEEPALIVE,  &ka,    sizeof(ka));
        setsockopt(c, IPPROTO_TCP, TCP_KEEPIDLE,  &idle,  sizeof(idle));
        setsockopt(c, IPPROTO_TCP, TCP_KEEPINTVL, &intvl, sizeof(intvl));
        setsockopt(c, IPPROTO_TCP, TCP_KEEPCNT,   &cnt,   sizeof(cnt));
        // Keep the buffered boot logs for the new client.
        ESP_LOGI(TAG, "log client connected");
        char buf[256];
        for (;;) {
            size_t n = xStreamBufferReceive(s_logbuf, buf, sizeof(buf), pdMS_TO_TICKS(500));
            if (n > 0) {
                if (send(c, buf, n, 0) < 0) break;
            } else {
                // Peek so a close is noticed without waiting for the next log line.
                char tmp[8];
                int pk = recv(c, tmp, sizeof(tmp), MSG_DONTWAIT | MSG_PEEK);
                if (pk == 0) break;                                       // peer closed
                if (pk < 0 && errno != EWOULDBLOCK && errno != EAGAIN) break;  // socket dead
            }
        }
        close(c);
    }
}

// ─── OTA upload (HTTP) ───
static esp_err_t root_get(httpd_req_t *req) {
    // The flash script matches this marker before sending, so brain firmware never
    // reaches the room node or the camera. Keep SANDY_BOARD_ID in step with it.
    static char page[240];
    snprintf(page, sizeof(page),
             "<h3>Sandy brain-core &middot; ESP32-S3</h3>"
             "<p>board-id: " SANDY_BOARD_ID "</p>"
             "<p>firmware: " SANDY_FW_VERSION "</p>"
             "<p>Flash: curl --data-binary @build/sandy-brain-s3.bin "
             "http://DEVICE_IP/update</p>");
    httpd_resp_send(req, page, HTTPD_RESP_USE_STRLEN);
    return ESP_OK;
}

static esp_err_t update_post(httpd_req_t *req) {
    const esp_partition_t *part = esp_ota_get_next_update_partition(NULL);
    if (!part) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "no OTA partition");
        return ESP_FAIL;
    }
    ESP_LOGI(TAG, "OTA -> %s (%d bytes)", part->label, req->content_len);

    esp_ota_handle_t h;
    if (esp_ota_begin(part, OTA_SIZE_UNKNOWN, &h) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "ota_begin failed");
        return ESP_FAIL;
    }

    // PSRAM, only for the upload: not the stack (overflow) nor a static (internal RAM voice needs).
    char *buf = heap_caps_malloc(1460, MALLOC_CAP_SPIRAM);
    if (!buf) {
        esp_ota_abort(h);
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "no buffer");
        return ESP_FAIL;
    }
    int remaining = req->content_len;
    while (remaining > 0) {
        int r = httpd_req_recv(req, buf, MIN(remaining, 1460));
        if (r == HTTPD_SOCK_ERR_TIMEOUT) continue;
        if (r <= 0) {
            free(buf); esp_ota_abort(h);
            httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "recv error");
            return ESP_FAIL;
        }
        if (esp_ota_write(h, buf, r) != ESP_OK) {
            free(buf); esp_ota_abort(h);
            httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "ota_write failed");
            return ESP_FAIL;
        }
        remaining -= r;
    }
    free(buf);

    if (esp_ota_end(h) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "image invalid");
        return ESP_FAIL;
    }
    if (esp_ota_set_boot_partition(part) != ESP_OK) {
        httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "set_boot failed");
        return ESP_FAIL;
    }
    httpd_resp_sendstr(req, "OK — rebooting into new firmware\n");
    // Flush deferred settings before the restart or they are lost.
    nvs_flush_deferred();
    ESP_LOGI(TAG, "OTA done — rebooting");
    vTaskDelay(pdMS_TO_TICKS(400));
    esp_restart();
    return ESP_OK;
}

static void start_http(void) {
    // Wait for an address: wifi_sandy_start() returns before association, and a
    // server bound too early answered nothing.
    for (int i = 0; i < 120 && !wifi_sandy_is_connected(); i++) {
        if (i % 20 == 0) ESP_LOGW(TAG, "http: waiting for an IP before binding");
        vTaskDelay(pdMS_TO_TICKS(500));
    }
    if (!wifi_sandy_is_connected()) {
        ESP_LOGE(TAG, "http: no IP after 60s — remote flashing unavailable");
        return;
    }

    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.lru_purge_enable = true;
    cfg.recv_wait_timeout = 20;
    // Default 4 KB stack; internal RAM is scarce.
    httpd_handle_t srv = NULL;
    if (httpd_start(&srv, &cfg) != ESP_OK) { ESP_LOGE(TAG, "httpd start failed"); return; }
    httpd_uri_t root = { .uri = "/",       .method = HTTP_GET,  .handler = root_get };
    httpd_uri_t upd  = { .uri = "/update", .method = HTTP_POST, .handler = update_post };
    httpd_register_uri_handler(srv, &root);
    httpd_register_uri_handler(srv, &upd);
    echo_probe_register(srv);
}

static void http_task(void *arg) {
    (void)arg;
    start_http();
    vTaskDelete(NULL);
}

esp_err_t remote_init(void) {
    // PSRAM, to spare internal RAM. Safe: esp_log never writes with the cache disabled.
    s_logbuf = xStreamBufferCreateWithCaps(LOG_BUF_BYTES, 1, MALLOC_CAP_SPIRAM);
    s_log_lock = xSemaphoreCreateMutex();
    s_old_vprintf = esp_log_set_vprintf(log_vprintf);
    // Stack in PSRAM (no flash access). The name "logsrv" is load-bearing:
    // publish_firmware.py checks retail images leave it out.
    if (xTaskCreateWithCaps(log_server_task, "logsrv", 4096, NULL, 4, NULL,
                            MALLOC_CAP_SPIRAM) != pdPASS) {
        xTaskCreate(log_server_task, "logsrv", 4096, NULL, 4, NULL);
    }
    // Own task so waiting for an address doesn't hold up boot. Small stack (internal RAM).
    xTaskCreate(http_task, "http_up", 2560, NULL, 4, NULL);
    ESP_LOGI(TAG, "remote ready — OTA: http://<ip>/update   logs: nc <ip> %d", LOG_PORT);
    return ESP_OK;
}

#endif // ENABLE_REMOTE
