// ESP32-CAM — صفحة الإعداد: شبكة احتياطية لمّا الشبكة المحفوظة ما بترد.
// نفس فكرة الدماغ (`sandy_provision.c`): بعد دقيقة ونص بلا شبكة بتطلع شبكة
// «Sandy-Cam-<الكود>» بكلمة سر «sandy<الكود>» (الكود ع العلبة)، وبتفتح صفحة ع
// http://192.168.4.1 بتختار منها الشبكة. التبديل نفسه `camSwitchNetwork` (بيجرّب
// وبيرجع للقديمة لو فشلت)، والشبكة الاحتياطية بتختفي لحالها أول ما ترجع الشبكة.

#include "esp_http_server.h"

#define CAM_SETUP_WINDOW_MS 90000
#define CAM_SETUP_TICK_MS   2000

static httpd_handle_t g_setupHttpd = NULL;
static bool           g_setupActive = false;
static unsigned long  g_setupLastOnlineMs = 0;
static unsigned long  g_setupLastTickMs = 0;
static String         g_setupOptions;   // آخر مسح، جاهز للصفحة

static String htmlEscape(const String& in) {
  String out;
  out.reserve(in.length() + 8);
  for (size_t i = 0; i < in.length(); i++) {
    char c = in[i];
    switch (c) {
      case '"':  out += "&quot;"; break;
      case '\'': out += "&#39;";  break;
      case '<':  out += "&lt;";   break;
      case '>':  out += "&gt;";   break;
      case '&':  out += "&amp;";  break;
      default:   out += c;        break;
    }
  }
  return out;
}

static int setupHexVal(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

// كلمات السر فيها `+` و`%` و`&` ومسافات.
static String formField(const String& body, const char* key) {
  String pat = String(key) + "=";
  int at = -1;
  for (int from = 0; (at = body.indexOf(pat, from)) >= 0; from = at + 1) {
    if (at == 0 || body[at - 1] == '&') break;
  }
  if (at < 0) return String();
  at += pat.length();
  int end = body.indexOf('&', at);
  String raw = body.substring(at, end < 0 ? body.length() : end);
  String out;
  for (size_t i = 0; i < raw.length(); i++) {
    char c = raw[i];
    if (c == '+') {
      out += ' ';
    } else if (c == '%' && i + 2 < raw.length() &&
               setupHexVal(raw[i + 1]) >= 0 && setupHexVal(raw[i + 2]) >= 0) {
      out += (char)(setupHexVal(raw[i + 1]) * 16 + setupHexVal(raw[i + 2]));
      i += 2;
    } else {
      out += c;
    }
  }
  return out;
}

static const char SETUP_PAGE_HEAD[] =
    "<!doctype html><html><head><meta charset=utf-8>"
    "<meta name=viewport content='width=device-width,initial-scale=1'>"
    "<title>Sandy camera</title><style>"
    "body{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:24px;"
    "background:#111;color:#eee}h1{font-size:20px;margin:0 0 4px}"
    "p{color:#999;margin:0 0 20px;font-size:14px}"
    "label{display:block;margin:14px 0 6px;font-size:14px}"
    "input{width:100%;box-sizing:border-box;padding:12px;font-size:16px;"
    "border-radius:10px;border:1px solid #333;background:#1c1c1c;color:#eee}"
    "button{width:100%;margin-top:22px;padding:14px;font-size:16px;border:0;"
    "border-radius:10px;background:#f5c518;color:#111;font-weight:600}"
    "</style></head><body><h1>Sandy camera</h1>"
    "<p>Choose the network the camera should join.</p>"
    "<form method=POST action=/setup>"
    "<label>Network</label><input name=ssid list=nets autocomplete=off required "
    "maxlength=32><datalist id=nets>";

static const char SETUP_PAGE_TAIL[] =
    "</datalist><label>Password</label>"
    "<input name=pass type=password maxlength=64 placeholder='Leave empty if open'>"
    "<button type=submit>Connect</button></form>"
    "<p style='margin-top:24px;font-size:12px'>It tests the network before saving. "
    "If it fails, it goes back to the old one and this page stays.</p></body></html>";

static esp_err_t setupReply(httpd_req_t* req, const char* title, const char* body) {
  String page = String("<!doctype html><meta charset=utf-8>"
                       "<meta name=viewport content='width=device-width,initial-scale=1'>"
                       "<body style=\"font-family:-apple-system,system-ui,sans-serif;"
                       "background:#111;color:#eee;padding:24px\">"
                       "<h1 style=font-size:20px>") + title +
                "</h1><p style=color:#999>" + body +
                "</p><p><a style=color:#f5c518 href=/>Back</a></p></body>";
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  httpd_resp_sendstr(req, page.c_str());
  return ESP_OK;
}

static esp_err_t setupRootGet(httpd_req_t* req) {
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  httpd_resp_send_chunk(req, SETUP_PAGE_HEAD, HTTPD_RESP_USE_STRLEN);
  if (g_setupOptions.length()) {
    httpd_resp_send_chunk(req, g_setupOptions.c_str(), g_setupOptions.length());
  }
  httpd_resp_send_chunk(req, SETUP_PAGE_TAIL, HTTPD_RESP_USE_STRLEN);
  httpd_resp_send_chunk(req, NULL, 0);
  return ESP_OK;
}

static esp_err_t setupPost(httpd_req_t* req) {
  // اسم ٣٢ وكلمة سر ٦٤، كلهن مرمّزات بالنسبة = ٢٩٠ وشوي.
  char body[320];
  int total = req->content_len;
  if (total <= 0 || total >= (int)sizeof(body)) {
    return setupReply(req, "Too long", "That did not fit. Try a shorter name.");
  }
  int got = 0;
  while (got < total) {
    int r = httpd_req_recv(req, body + got, total - got);
    if (r <= 0) return setupReply(req, "Interrupted", "The form did not arrive whole.");
    got += r;
  }
  body[got] = '\0';

  String form(body);
  if (!camQueueWifi(formField(form, "ssid"), formField(form, "pass"))) {
    return setupReply(req, "Not accepted",
                      "Pick a network name; a password is empty or 8 to 64 characters.");
  }
  return setupReply(req, "Connecting…",
                    "If it works, this network disappears and the camera is back on yours. "
                    "If not, this page comes back in about half a minute.");
}

// المسح بيحجز ثانيتين تلاتة؛ من الحلقة بس.
static void setupScan() {
  int n = WiFi.scanNetworks(false, false);
  String opts;
  for (int i = 0; i < n && i < 20; i++) {
    String ssid = WiFi.SSID(i);
    if (!ssid.length()) continue;
    // أسماء الشبكات بيكتبها أي حدا: بتنهرب.
    opts += "<option value=\"" + htmlEscape(ssid) + "\">";
  }
  WiFi.scanDelete();
  g_setupOptions = opts;
}

static void setupStart() {
  // لو خادم البث لسا ماسك المنفذ، منستنّى لحدّ ما يطفي لحاله.
  if (camHttpRunning()) return;

  String code = g_id.pair.length() ? g_id.pair : String("0000");
  String ssid = "Sandy-Cam-" + code;
  // البادئة بس لتكمّل ثمانية أحرف (حد WPA2)؛ الكود ع العلبة، مش سر.
  String pass = "sandy" + code;
  if (pass.length() < 8) pass = "sandysetup";

  WiFi.mode(WIFI_AP_STA);   // الطرف العادي ضروري للمسح ولتجربة الشبكة المختارة
  if (!WiFi.softAP(ssid.c_str(), pass.c_str(), 1, 0, 2)) {
    g_log.println("[SETUP] ما قدرنا نطلّع الشبكة الاحتياطية");
    WiFi.mode(WIFI_STA);
    return;
  }

  // قبل الخادم: الصفحة بتقرا القائمة من مهمّة تانية.
  setupScan();

  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.server_port = 80;
  cfg.ctrl_port = 32770;   // غير منفذ تحكّم خادم البث
  cfg.lru_purge_enable = true;
  cfg.stack_size = 6144;
  if (httpd_start(&g_setupHttpd, &cfg) != ESP_OK) {
    g_log.println("[SETUP] المنفذ مشغول — بنرجع نجرّب");
    g_setupHttpd = NULL;
    WiFi.softAPdisconnect(true);
    WiFi.mode(WIFI_STA);
    return;
  }
  httpd_uri_t root = {};
  root.uri = "/";      root.method = HTTP_GET;  root.handler = setupRootGet;
  httpd_register_uri_handler(g_setupHttpd, &root);
  httpd_uri_t post = {};
  post.uri = "/setup"; post.method = HTTP_POST; post.handler = setupPost;
  httpd_register_uri_handler(g_setupHttpd, &post);

  g_setupActive = true;
  // كلمة السر مش بالسجل.
  g_log.printf("[SETUP] ما في شبكة — ادخل ع '%s' وافتح http://192.168.4.1\n", ssid.c_str());
}

static void setupStop() {
  if (g_setupHttpd) { httpd_stop(g_setupHttpd); g_setupHttpd = NULL; }
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_STA);
  g_setupActive = false;
  g_setupOptions = "";
  g_log.println("[SETUP] الشبكة رجعت — صفحة الإعداد سكّرت");
}

void camSetupTick() {
  unsigned long now = millis();
  if (now - g_setupLastTickMs < CAM_SETUP_TICK_MS) return;
  g_setupLastTickMs = now;

  if (WiFi.status() == WL_CONNECTED) {
    g_setupLastOnlineMs = now;
    if (g_setupActive) setupStop();
    return;
  }
  if (g_setupActive) return;
  // بلا شبكة محفوظة ما في شي نستنّاه.
  bool haveSsid = camSsid()[0] != '\0';
  if (haveSsid && now - g_setupLastOnlineMs < CAM_SETUP_WINDOW_MS) return;
  setupStart();
}
