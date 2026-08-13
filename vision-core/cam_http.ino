// =========================
// ESP32-CAM — HTTP: live video stream + instant still
// =========================
// الفيديو ما بينفع عبر MQTT: كل إطار بينقسم لعشرات الرسائل وبيخنق البروكر.
// فالبث بيمشي مباشرة عبر الشبكة المحلية، والـMQTT بيضل للصور المفردة والأوامر.
//
//   GET /stream   → بث مباشر (MJPEG) — يفتح بأي متصفح
//   GET /still    → صورة وحدة فوراً (JPEG)
//   GET /status   → حالة مختصرة (JSON)
//
// الخادم مطفي افتراضياً. بينشغل بأمر: {"cmd":"stream","state":"on"}
// وبيطفي لحاله بعد فترة بلا متفرّجين — عشان ما يضل ياكل ذاكرة وحرارة.

#include "esp_http_server.h"

// ── إعلانات من ملفات تانية ──
bool flashWantedForCapture(FlashMode mode);
void flashSet(uint8_t level, unsigned long autoOffMs);
void flashOff();

static httpd_handle_t g_httpd = NULL;
static volatile unsigned long g_lastStreamActivityMs = 0;
static volatile bool g_streamViewerActive = false;

#define STREAM_BOUNDARY "sandyframe"
static const char* kStreamContentType =
    "multipart/x-mixed-replace;boundary=" STREAM_BOUNDARY;
static const char* kStreamBoundary = "\r\n--" STREAM_BOUNDARY "\r\n";
static const char* kStreamPartFmt =
    "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

// التوكن اختياري: لو فاضي بالإعدادات، الخادم مفتوح داخل الشبكة المحلية فقط.
static bool authorized(httpd_req_t* req) {
  if (strlen(CAM_HTTP_TOKEN) == 0) return true;

  size_t qlen = httpd_req_get_url_query_len(req) + 1;
  if (qlen <= 1) return false;

  char* query = (char*)malloc(qlen);
  if (!query) return false;
  bool ok = false;
  if (httpd_req_get_url_query_str(req, query, qlen) == ESP_OK) {
    char token[64] = {0};
    if (httpd_query_key_value(query, "token", token, sizeof(token)) == ESP_OK) {
      ok = (strcmp(token, CAM_HTTP_TOKEN) == 0);
    }
  }
  free(query);
  return ok;
}

static esp_err_t denied(httpd_req_t* req) {
  httpd_resp_set_status(req, "403 Forbidden");
  httpd_resp_send(req, "forbidden", HTTPD_RESP_USE_STRLEN);
  return ESP_OK;
}

static esp_err_t stillHandler(httpd_req_t* req) {
  if (!authorized(req)) return denied(req);
  if (!g_cameraReady) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    httpd_resp_send(req, "camera not ready", HTTPD_RESP_USE_STRLEN);
    return ESP_OK;
  }

  bool useFlash = flashWantedForCapture(g_flashMode);
  if (useFlash) {
    flashSet(g_flashLevel, FLASH_WARMUP_MS + 400);
    delay(FLASH_WARMUP_MS);
  }

  camera_fb_t* fb = esp_camera_fb_get();
  if (useFlash) flashOff();

  if (!fb) {
    httpd_resp_set_status(req, "500 Internal Server Error");
    httpd_resp_send(req, "capture failed", HTTPD_RESP_USE_STRLEN);
    return ESP_OK;
  }

  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=sandy.jpg");
  esp_err_t rc = httpd_resp_send(req, (const char*)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  return rc;
}

static esp_err_t streamHandler(httpd_req_t* req) {
  if (!authorized(req)) return denied(req);
  if (!g_cameraReady) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    httpd_resp_send(req, "camera not ready", HTTPD_RESP_USE_STRLEN);
    return ESP_OK;
  }

  esp_err_t rc = httpd_resp_set_type(req, kStreamContentType);
  if (rc != ESP_OK) return rc;
  httpd_resp_set_hdr(req, "Access-Control-Allow-Origin", "*");

  g_streamViewerActive = true;
  char part[64];

  while (true) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { rc = ESP_FAIL; break; }

    size_t hlen = snprintf(part, sizeof(part), kStreamPartFmt, fb->len);
    rc = httpd_resp_send_chunk(req, kStreamBoundary, strlen(kStreamBoundary));
    if (rc == ESP_OK) rc = httpd_resp_send_chunk(req, part, hlen);
    if (rc == ESP_OK) rc = httpd_resp_send_chunk(req, (const char*)fb->buf, fb->len);
    esp_camera_fb_return(fb);

    if (rc != ESP_OK) break;         // المتفرّج سكّر الصفحة
    g_lastStreamActivityMs = millis();
    delay(1);                        // yield للشبكة
  }

  g_streamViewerActive = false;
  g_lastStreamActivityMs = millis();
  return rc;
}

static esp_err_t statusHandler(httpd_req_t* req) {
  if (!authorized(req)) return denied(req);
  char buf[220];
  snprintf(buf, sizeof(buf),
           "{\"uptime_s\":%lu,\"rssi\":%d,\"heap\":%u,\"camera_ready\":%s,"
           "\"streaming\":%s}",
           millis() / 1000, WiFi.RSSI(), ESP.getFreeHeap(),
           g_cameraReady ? "true" : "false",
           g_streamViewerActive ? "true" : "false");
  httpd_resp_set_type(req, "application/json");
  httpd_resp_send(req, buf, HTTPD_RESP_USE_STRLEN);
  return ESP_OK;
}

bool camHttpRunning() { return g_httpd != NULL; }

void startCamHttp() {
  if (g_httpd) return;

  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.server_port = CAM_HTTP_PORT;
  cfg.ctrl_port = CAM_HTTP_PORT + 1000;
  cfg.max_uri_handlers = 4;
  cfg.stack_size = 8192;

  if (httpd_start(&g_httpd, &cfg) != ESP_OK) {
    g_log.println("[HTTP] failed to start");
    g_httpd = NULL;
    return;
  }

  httpd_uri_t route = {};
  route.method = HTTP_GET;
  route.user_ctx = NULL;

  route.uri = "/stream";  route.handler = streamHandler;
  httpd_register_uri_handler(g_httpd, &route);
  route.uri = "/still";   route.handler = stillHandler;
  httpd_register_uri_handler(g_httpd, &route);
  route.uri = "/status";  route.handler = statusHandler;
  httpd_register_uri_handler(g_httpd, &route);

  g_lastStreamActivityMs = millis();
  g_log.printf("[HTTP] up → http://%s/stream\n", WiFi.localIP().toString().c_str());
}

void stopCamHttp() {
  if (!g_httpd) return;
  httpd_stop(g_httpd);
  g_httpd = NULL;
  g_streamViewerActive = false;
  g_log.println("[HTTP] stopped");
}

// تُنادى من الـ loop — تطفي الخادم لما ما يضل حدا متفرّج
void camHttpTick() {
  if (!g_httpd || g_streamViewerActive) return;
  if (millis() - g_lastStreamActivityMs > CAM_STREAM_IDLE_TIMEOUT_MS) {
    g_log.println("[HTTP] idle — shutting the stream server down");
    stopCamHttp();
  }
}
