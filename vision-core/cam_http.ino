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
//
// **وكل طلب لازم يحمل مفتاح البث** (`?key=` أو ترويسة `X-Sandy-Key`). المفتاح
// عشوائي، بيتولّد كل إقلاع، وبيوصل الخادم بالنبضة، والخادم بيعطيه لصاحب
// الروبوت بس. جهاز تاني ع نفس الشبكة — تلفزيون، قابس ذكي مخترق، ضيف — ما
// بيعرفه، فما بيشوف إشي.

#include "esp_http_server.h"
#include "esp_random.h"

// ── إعلانات من ملفات تانية ──
bool flashWantedForCapture(FlashMode mode);
void flashSet(uint8_t level, unsigned long autoOffMs);
void flashOff();
bool camLock(uint32_t waitMs);
void camUnlock();

static httpd_handle_t g_httpd = NULL;
static volatile unsigned long g_lastStreamActivityMs = 0;
// إشارة «وقّف» لحلقة البث. `httpd_stop` بيستنّى مهمّة الخادم تخلص، وهي عالقة
// جوّا حلقة البث اللي ما بتطلع إلا لمّا الإرسال يفشل — يعني وإنت عم تتفرّج،
// «وقّف البث» كان بيعلّق الحلقة الرئيسية كلها للأبد.
static volatile bool g_streamStop = false;
static char g_streamKey[33] = {0};
// مش `static`: البثّ البعيد بيقراها عشان ما ينازع المتفرّج المحلي ع مخزن
// الإطار الوحيد.
volatile bool g_streamViewerActive = false;

#define STREAM_BOUNDARY "sandyframe"
static const char* kStreamContentType =
    "multipart/x-mixed-replace;boundary=" STREAM_BOUNDARY;
static const char* kStreamBoundary = "\r\n--" STREAM_BOUNDARY "\r\n";
static const char* kStreamPartFmt =
    "Content-Type: image/jpeg\r\nContent-Length: %u\r\n\r\n";

// المفتاح اللي الخادم بيوزّعه للتطبيق. مولّد مرّة بكل إقلاع (أو من الأسرار
// لنسخ التطوير)، وثابت طول التشغيل عشان التطبيق ما يلحق وراه.
const char* camStreamKey() {
  if (g_streamKey[0]) return g_streamKey;
  if (strlen(CAM_HTTP_TOKEN) > 0) {
    strncpy(g_streamKey, CAM_HTTP_TOKEN, sizeof(g_streamKey) - 1);
    return g_streamKey;
  }
  for (int i = 0; i < 4; i++) {
    snprintf(g_streamKey + i * 8, 9, "%08lx", (unsigned long)esp_random());
  }
  return g_streamKey;
}

// مقارنة بزمن ثابت: مقارنة عادية بتوقف عند أول حرف مختلف، والوقت اللي بتاخده
// بيسرّب قدّيش الحرزة صح.
static bool keyEquals(const char* a, const char* b) {
  size_t la = strlen(a), lb = strlen(b);
  unsigned char diff = (unsigned char)(la ^ lb);
  for (size_t i = 0; i < la && i < lb; i++) diff |= (unsigned char)(a[i] ^ b[i]);
  return diff == 0 && la > 0;
}

static bool authorized(httpd_req_t* req) {
  const char* want = camStreamKey();
  char got[48] = {0};

  if (httpd_req_get_hdr_value_str(req, "X-Sandy-Key", got, sizeof(got)) == ESP_OK) {
    return keyEquals(got, want);
  }

  size_t qlen = httpd_req_get_url_query_len(req) + 1;
  if (qlen <= 1 || qlen > 256) return false;
  char query[256];
  if (httpd_req_get_url_query_str(req, query, qlen) != ESP_OK) return false;
  if (httpd_query_key_value(query, "key", got, sizeof(got)) != ESP_OK) return false;
  return keyEquals(got, want);
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

  if (!camLock(3000)) {
    httpd_resp_set_status(req, "503 Service Unavailable");
    httpd_resp_send(req, "camera busy", HTTPD_RESP_USE_STRLEN);
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
    camUnlock();
    httpd_resp_set_status(req, "500 Internal Server Error");
    httpd_resp_send(req, "capture failed", HTTPD_RESP_USE_STRLEN);
    return ESP_OK;
  }

  httpd_resp_set_type(req, "image/jpeg");
  httpd_resp_set_hdr(req, "Content-Disposition", "inline; filename=sandy.jpg");
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");
  esp_err_t rc = httpd_resp_send(req, (const char*)fb->buf, fb->len);
  esp_camera_fb_return(fb);
  camUnlock();
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
  // ما في `Access-Control-Allow-Origin: *` بعد اليوم: كان بيسمح لأي صفحة ويب
  // مفتوحة ع أي جهاز بالبيت تقرا الإطارات بسكربت.
  httpd_resp_set_hdr(req, "Cache-Control", "no-store");

  g_streamViewerActive = true;
  unsigned long startedAt = millis();
  char part[64];

  while (!g_streamStop) {
    if (millis() - startedAt > CAM_LOCAL_STREAM_MAX_MS) {
      g_log.println("[HTTP] جلسة البث المحلي وصلت سقفها — وقّفناها");
      break;
    }
    // الإطار تحت القفل، والإرسال برّاه: الالتقاط ما بيستنّى شبكة المتفرّج.
    if (!camLock(1000)) { delay(20); continue; }
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) { camUnlock(); rc = ESP_FAIL; break; }
    size_t flen = fb->len;
    size_t hlen = snprintf(part, sizeof(part), kStreamPartFmt, (unsigned)flen);
    rc = httpd_resp_send_chunk(req, kStreamBoundary, strlen(kStreamBoundary));
    if (rc == ESP_OK) rc = httpd_resp_send_chunk(req, part, hlen);
    if (rc == ESP_OK) rc = httpd_resp_send_chunk(req, (const char*)fb->buf, flen);
    esp_camera_fb_return(fb);
    camUnlock();

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
           millis() / 1000, WiFi.RSSI(), (unsigned)ESP.getFreeHeap(),
           g_cameraReady ? "true" : "false",
           g_streamViewerActive ? "true" : "false");
  httpd_resp_set_type(req, "application/json");
  httpd_resp_send(req, buf, HTTPD_RESP_USE_STRLEN);
  return ESP_OK;
}

bool camHttpRunning() { return g_httpd != NULL; }

void startCamHttp() {
  if (g_httpd) return;
  g_streamStop = false;

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
  // العنوان بلا المفتاح: السجل مش المكان اللي بيوصل منه المفتاح لحدا.
  g_log.printf("[HTTP] up → http://%s/stream\n", WiFi.localIP().toString().c_str());
}

void stopCamHttp() {
  if (!g_httpd) return;
  // الإشارة قبل الإيقاف: حلقة البث بتشوفها بالإطار الجاي وبتطلع، فـ`httpd_stop`
  // بيلاقي المهمّة فاضية بدل ما يستنّاها للأبد.
  g_streamStop = true;
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
