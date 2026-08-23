#include "config.h"
#if ENABLE_PROVISION

#include "sandy_provision.h"
#include "sandy_wifi.h"
#include "sandy_screen.h"
#include "sandy_status.h"
#include "secrets.h"

#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#include "esp_wifi.h"
#include "esp_netif.h"
#include "esp_log.h"
#include "esp_http_server.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

static const char *TAG = "provision";

static httpd_handle_t s_httpd = NULL;
static volatile bool  s_active = false;
static char           s_ap_ssid[33];

bool provision_is_active(void) { return s_active; }

// ─── The access point's identity ─────────────────────────────────────────────
//
// Named after the code printed on the box, so the owner finds it without being
// told which of the neighbourhood's networks is the robot. "Sandy-8421" next to
// a sticker that says 8421 needs no instructions.
//
// WPA2, not open. An open setup network hands anyone in range the list of
// networks this house can see and a form that sets which one the robot joins.
// The password is derived from the same code — printed on the same sticker —
// which is weak against someone who has read the box and worth far more than
// nothing against everyone who has not.
static void build_ap_identity(char *ssid, size_t ssid_cap,
                              char *pass, size_t pass_cap) {
    snprintf(ssid, ssid_cap, "Sandy-%s", SANDY_PAIR_CODE);
    // WPA2 refuses anything under eight characters, and a short pairing code is
    // common. The prefix is what makes it long enough; it is not a secret.
    snprintf(pass, pass_cap, "sandy%s", SANDY_PAIR_CODE);
    if (strlen(pass) < 8) snprintf(pass, pass_cap, "sandysetup");
}

// ─── The page ────────────────────────────────────────────────────────────────
//
// Plain HTML in one string, no assets, no network calls. Whatever the owner's
// phone is, it has a browser, and this has to work on the one network in the
// world that cannot reach the internet.
static const char PAGE_HEAD[] =
    "<!doctype html><html><head><meta charset=utf-8>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>Sandy</title><style>"
    "body{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:24px;"
    "background:#111;color:#eee}h1{font-size:20px;margin:0 0 4px}"
    "p{color:#999;margin:0 0 20px;font-size:14px}"
    "label{display:block;margin:14px 0 6px;font-size:14px}"
    "select,input{width:100%;box-sizing:border-box;padding:12px;font-size:16px;"
    "border-radius:10px;border:1px solid #333;background:#1c1c1c;color:#eee}"
    "button{width:100%;margin-top:22px;padding:14px;font-size:16px;border:0;"
    "border-radius:10px;background:#f5c518;color:#111;font-weight:600}"
    "</style></head><body><h1>Sandy</h1>"
    "<p>Choose the network she should join.</p>"
    "<form method=POST action=/provision>"
    "<label>Network</label><select name=ssid>";

static const char PAGE_TAIL[] =
    "</select>"
    "<label>Password</label>"
    "<input name=pass type=password placeholder='Leave empty if open'>"
    "<button type=submit>Connect</button></form>"
    "<p style='margin-top:24px;font-size:12px'>She will test it before saving. "
    "If it fails, this page comes back.</p></body></html>";

// A scan runs on demand rather than being cached at boot: the owner may well be
// standing next to the router they just turned on.
static esp_err_t root_get(httpd_req_t *req) {
    wifi_scan_config_t scan = { .show_hidden = false };
    uint16_t n = 0;
    wifi_ap_record_t *aps = NULL;

    if (esp_wifi_scan_start(&scan, true) == ESP_OK &&
        esp_wifi_scan_get_ap_num(&n) == ESP_OK && n) {
        if (n > 20) n = 20;
        aps = calloc(n, sizeof(*aps));
        if (aps && esp_wifi_scan_get_ap_records(&n, aps) != ESP_OK) {
            free(aps);
            aps = NULL;
        }
    }

    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_send_chunk(req, PAGE_HEAD, HTTPD_RESP_USE_STRLEN);

    if (aps) {
        for (uint16_t i = 0; i < n; i++) {
            const char *ssid = (const char *)aps[i].ssid;
            if (!ssid[0]) continue;
            // Escaping is not decoration here: a network named with a quote
            // would otherwise break the option out of its own tag, and the
            // names on the air are written by strangers.
            char opt[160];
            int k = snprintf(opt, sizeof(opt), "<option value=\"");
            for (const char *p = ssid; *p && k < (int)sizeof(opt) - 24; p++) {
                if (*p == '"')      k += snprintf(opt + k, sizeof(opt) - k, "&quot;");
                else if (*p == '<') k += snprintf(opt + k, sizeof(opt) - k, "&lt;");
                else if (*p == '&') k += snprintf(opt + k, sizeof(opt) - k, "&amp;");
                else                opt[k++] = *p, opt[k] = '\0';
            }
            k += snprintf(opt + k, sizeof(opt) - k, "\">%s</option>", ssid);
            httpd_resp_send_chunk(req, opt, k);
        }
        free(aps);
    } else {
        httpd_resp_send_chunk(req,
            "<option value=\"\">— no networks found —</option>",
            HTTPD_RESP_USE_STRLEN);
    }

    httpd_resp_send_chunk(req, PAGE_TAIL, HTTPD_RESP_USE_STRLEN);
    httpd_resp_send_chunk(req, NULL, 0);
    return ESP_OK;
}

// ─── Form decoding ───────────────────────────────────────────────────────────

static int hexval(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

// Percent-decoding, in place-ish. Wi-Fi passwords are exactly the strings that
// contain the characters a form encodes — `+`, `%`, `&`, spaces — so skipping
// this would fail on precisely the passwords people actually choose.
static void url_decode(const char *src, char *dst, size_t cap) {
    size_t j = 0;
    for (size_t i = 0; src[i] && j + 1 < cap; i++) {
        if (src[i] == '+') {
            dst[j++] = ' ';
        } else if (src[i] == '%' && src[i + 1] && src[i + 2]) {
            int hi = hexval(src[i + 1]), lo = hexval(src[i + 2]);
            if (hi >= 0 && lo >= 0) { dst[j++] = (char)(hi * 16 + lo); i += 2; }
            else                     dst[j++] = src[i];
        } else {
            dst[j++] = src[i];
        }
    }
    dst[j] = '\0';
}

static void form_field(const char *body, const char *key, char *out, size_t cap) {
    out[0] = '\0';
    char pat[16];
    int pn = snprintf(pat, sizeof(pat), "%s=", key);
    const char *p = body;
    while ((p = strstr(p, pat))) {
        if (p == body || p[-1] == '&') break;
        p += pn;
    }
    if (!p) return;
    p += pn;
    const char *end = strchr(p, '&');
    size_t len = end ? (size_t)(end - p) : strlen(p);

    char raw[160];
    if (len >= sizeof(raw)) len = sizeof(raw) - 1;
    memcpy(raw, p, len);
    raw[len] = '\0';
    url_decode(raw, out, cap);
}

static esp_err_t reply(httpd_req_t *req, const char *title, const char *body) {
    char page[512];
    snprintf(page, sizeof(page),
             "<!doctype html><meta charset=utf-8>"
             "<meta name=viewport content='width=device-width,initial-scale=1'>"
             "<body style=\"font-family:-apple-system,system-ui,sans-serif;"
             "background:#111;color:#eee;padding:24px\">"
             "<h1 style=font-size:20px>%s</h1><p style=color:#999>%s</p>"
             "<p><a style=color:#f5c518 href=/>Back</a></p></body>",
             title, body);
    httpd_resp_set_type(req, "text/html; charset=utf-8");
    httpd_resp_sendstr(req, page);
    return ESP_OK;
}

// ─── Accepting a network ─────────────────────────────────────────────────────

static esp_err_t provision_post(httpd_req_t *req) {
    char body[320];
    int total = req->content_len;
    if (total <= 0 || total >= (int)sizeof(body)) {
        return reply(req, "Too long", "That did not fit. Try a shorter name.");
    }
    int got = 0;
    while (got < total) {
        int r = httpd_req_recv(req, body + got, total - got);
        if (r <= 0) return reply(req, "Interrupted", "The form did not arrive whole.");
        got += r;
    }
    body[got] = '\0';

    char ssid[33] = "", pass[65] = "";
    form_field(body, "ssid", ssid, sizeof(ssid));
    form_field(body, "pass", pass, sizeof(pass));

    if (!ssid[0]) {
        return reply(req, "Pick a network", "No network was selected.");
    }

    ESP_LOGI(TAG, "trying '%s' from the setup page", ssid);
    screen_show_text("Testing…");

    // **Answer before switching radios.** wifi_sandy_switch tears down the
    // association this very page is being served over, so a reply written after
    // it returns is a reply the phone never sees — the browser shows a failure
    // for a setup that worked. The verdict goes on the screen and in the log;
    // the page says what is about to happen.
    reply(req, "Connecting…",
          "Watch her screen. If it worked she restarts on your network; "
          "if not, this page comes back in a few seconds.");
    vTaskDelay(pdMS_TO_TICKS(300));

    wifi_switch_result_t r = wifi_sandy_switch(ssid, pass);
    if (r == WIFI_SWITCH_OK) {
        ESP_LOGW(TAG, "'%s' accepted — restarting on it", ssid);
        screen_show_text("Connected");
        vTaskDelay(pdMS_TO_TICKS(1200));
        esp_restart();
    }

    ESP_LOGW(TAG, "'%s' refused (%d) — staying in setup", ssid, (int)r);
    screen_show_text("Wrong password?");
    return ESP_OK;
}

// ─── Bringing the access point up ────────────────────────────────────────────

static void start_ap(void) {
    char pass[65];
    build_ap_identity(s_ap_ssid, sizeof(s_ap_ssid), pass, sizeof(pass));

    esp_netif_create_default_wifi_ap();

    wifi_config_t ap = { 0 };
    size_t sn = strlen(s_ap_ssid);
    if (sn > sizeof(ap.ap.ssid)) sn = sizeof(ap.ap.ssid);
    memcpy(ap.ap.ssid, s_ap_ssid, sn);
    ap.ap.ssid_len = sn;
    size_t pn = strlen(pass);
    if (pn > sizeof(ap.ap.password)) pn = sizeof(ap.ap.password);
    memcpy(ap.ap.password, pass, pn);
    ap.ap.max_connection = 2;
    ap.ap.authmode = WIFI_AUTH_WPA2_PSK;
    ap.ap.channel = 1;

    // APSTA, not AP: the station side has to stay alive to scan for the networks
    // the page lists, and to test the one the owner picks. In plain AP mode the
    // scan returns nothing and every choice fails for a reason nobody can see.
    esp_wifi_set_mode(WIFI_MODE_APSTA);
    esp_wifi_set_config(WIFI_IF_AP, &ap);

    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.lru_purge_enable = true;
    // Above the 4 KB default: the POST handler holds the body, a decode buffer
    // and the reply page at the same time, and a stack overflow here would show
    // up as a reboot in the middle of setup — the least debuggable moment there
    // is, on a board with no network and an owner with no log.
    cfg.stack_size = 6144;
    if (httpd_start(&s_httpd, &cfg) != ESP_OK) {
        // Port 80 may still be held by the remote-flash server from a session
        // that had a network. Not fatal and not silent: the retry loop tries
        // again, and a robot that cannot serve the page has to say so.
        ESP_LOGE(TAG, "cannot bind the setup page — port 80 busy");
        s_httpd = NULL;
        return;
    }
    httpd_uri_t root = { .uri = "/",          .method = HTTP_GET,  .handler = root_get };
    httpd_uri_t post = { .uri = "/provision", .method = HTTP_POST, .handler = provision_post };
    httpd_register_uri_handler(s_httpd, &root);
    httpd_register_uri_handler(s_httpd, &post);

    s_active = true;
    status_set(SANDY_ST_NO_WIFI);

    // The instruction goes on her face. A robot that needs setup and says
    // nothing is indistinguishable from a robot that is broken, and the owner's
    // next move is the box, not the phone.
    char msg[96];
    snprintf(msg, sizeof(msg), "Wi-Fi setup — join %s", s_ap_ssid);
    screen_show_text(msg);

    ESP_LOGW(TAG, "setup mode — join '%s' (password '%s') and open http://192.168.4.1",
             s_ap_ssid, pass);
}

static void stop_ap(void) {
    if (s_httpd) { httpd_stop(s_httpd); s_httpd = NULL; }
    esp_wifi_set_mode(WIFI_MODE_STA);
    s_active = false;
    ESP_LOGI(TAG, "network found — setup mode off");
}

// ─── The watcher ─────────────────────────────────────────────────────────────

static void provision_task(void *arg) {
    (void)arg;

    // Give the saved network its chance first. A robot that raises a setup
    // network every time the router is slow to wake would be worse than one
    // that never does: the owner would find it in setup mode most mornings.
    const int step_ms = 500;
    int waited = 0;
    while (waited < PROVISION_WINDOW_MS) {
        if (wifi_sandy_is_connected()) {
            ESP_LOGI(TAG, "connected within the window — no setup needed");
            vTaskDelete(NULL);
        }
        vTaskDelay(pdMS_TO_TICKS(step_ms));
        waited += step_ms;
    }

    ESP_LOGW(TAG, "no network after %d s — raising the setup access point",
             PROVISION_WINDOW_MS / 1000);
    start_ap();

    // Stay up, but yield the moment the real network comes back: a router that
    // rebooted should not leave the robot camped on its own island waiting for
    // a person. Whoever gets there first wins, and neither needs a human.
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(2000));
        if (wifi_sandy_is_connected()) {
            stop_ap();
            vTaskDelete(NULL);
        }
        if (!s_httpd) start_ap();   // port was busy last time; try again
    }
}

esp_err_t provision_init(void) {
    return xTaskCreate(provision_task, "provision", 4096, NULL, 3, NULL) == pdPASS
           ? ESP_OK : ESP_ERR_NO_MEM;
}

#endif  // ENABLE_PROVISION
