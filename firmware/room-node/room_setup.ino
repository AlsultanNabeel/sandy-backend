// Room node — صفحة الإعداد: شبكة احتياطية لمّا الشبكة المحفوظة ما بترد. نفس الكاميرا
// (`vision-core/cam_setup.ino`): بعد دقيقة ونص بلا شبكة (أو فورًا بلا شبكة محفوظة) بتطلع
// شبكة «Sandy-Room-<آخر أربع خانات من الكود>» بكلمة سر «sandy<الكود كامل>» (الكود ع العلبة)،
// وصفحة ع http://192.168.4.1 بتختار منها الشبكة. التبديل نفسه `roomSwitchNetwork` (بيجرّب
// وبيرجع للقديمة)، والشبكة الاحتياطية بتختفي لحالها أول ما ترجع الشبكة. شبكة شغّالة بلا وسيط
// عشر دقايق بتطلّعها كمان، وأول ردّ من الوسيط بيرجّعها.

#define ROOM_SETUP_WINDOW_MS    90000UL
#define ROOM_SETUP_TICK_MS      2000UL
#define ROOM_SETUP_NO_SERVER_MS (10UL * 60UL * 1000UL)
#define ROOM_SETUP_PROBE_MS     60000UL
#define ROOM_SETUP_SCAN_WAIT_MS 6000

static httpd_handle_t   g_setupHttpd = NULL;
static bool             g_setupActive = false;
static bool             g_setupForServer = false;   // طالعة لأنه ما في وسيط، والشبكة شغّالة
static unsigned long    g_setupLastOnlineMs = 0;
static unsigned long    g_setupLastServerMs = 0;
static unsigned long    g_setupLastProbeMs = 0;
static unsigned long    g_setupLastTickMs = 0;
static String           g_setupOptions;             // آخر مسح، جاهز للصفحة
static SemaphoreHandle_t g_setupLock = NULL;        // بتنكتب بالحلقة وبتنقرا بمهمّة الصفحة
static volatile bool     g_setupScanWanted = false;
static volatile uint32_t g_setupScanGen = 0;

bool roomSetupActive() { return g_setupActive; }

static String setupHtmlEscape(const String& in) {
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
static String setupFormField(const String& body, const char* key) {
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
    "<title>Sandy room</title><style>"
    "body{font-family:-apple-system,system-ui,sans-serif;margin:0;padding:24px;"
    "background:#111;color:#eee}h1{font-size:20px;margin:0 0 4px}"
    "p{color:#999;margin:0 0 20px;font-size:14px}"
    "label{display:block;margin:14px 0 6px;font-size:14px}"
    "input{width:100%;box-sizing:border-box;padding:12px;font-size:16px;"
    "border-radius:10px;border:1px solid #333;background:#1c1c1c;color:#eee}"
    "button{width:100%;margin-top:22px;padding:14px;font-size:16px;border:0;"
    "border-radius:10px;background:#f5c518;color:#111;font-weight:600}"
    ".ar{direction:rtl;text-align:right}"
    "</style></head><body><h1>Sandy room · غرفة ساندي</h1>"
    "<p>Choose the network the room node should join.</p>"
    "<p class=ar>اختار الشبكة اللي بدها تدخل عليها عقدة الغرفة.</p>"
    "<form method=POST action=/setup>"
    "<label>Network · الشبكة</label><input name=ssid list=nets autocomplete=off required "
    "maxlength=32><datalist id=nets>";

static const char SETUP_PAGE_TAIL[] =
    "</datalist><label>Password · كلمة السر</label>"
    "<input name=pass type=password maxlength=64 "
    "placeholder='Leave empty if open · فاضية إذا مفتوحة'>"
    "<button type=submit>Connect · اتصل</button></form>"
    "<p style='margin-top:24px;font-size:12px'>It tests the network, and that it reaches "
    "Sandy through it, before saving. If it fails, it goes back and this page stays.</p>"
    "<p class=ar style='font-size:12px'>بتجرّبها، وبتتأكّد إنه في إنترنت منها، قبل ما "
    "تحفظها. إذا ما زبطت، بترجع للقديمة وهالصفحة بتضل.</p></body></html>";

static esp_err_t setupReply(httpd_req_t* req, const char* title, const char* body,
                            const char* titleAr, const char* bodyAr) {
  String page = String("<!doctype html><meta charset=utf-8>"
                       "<meta name=viewport content='width=device-width,initial-scale=1'>"
                       "<body style=\"font-family:-apple-system,system-ui,sans-serif;"
                       "background:#111;color:#eee;padding:24px\">"
                       "<h1 style=font-size:20px>") + title +
                "</h1><p style=color:#999>" + body +
                "</p><div dir=rtl><h1 style=font-size:20px>" + titleAr +
                "</h1><p style=color:#999>" + bodyAr +
                "</p></div><p><a style=color:#f5c518 href=/>Back · رجوع</a></p></body>";
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  httpd_resp_sendstr(req, page.c_str());
  return ESP_OK;
}

static esp_err_t setupRootGet(httpd_req_t* req) {
  // مسح جديد مع كل فتح، من الحلقة؛ الصفحة بتستنّاه.
  uint32_t gen = g_setupScanGen;
  g_setupScanWanted = true;
  for (int waited = 0; g_setupScanGen == gen && waited < ROOM_SETUP_SCAN_WAIT_MS; waited += 100) {
    vTaskDelay(pdMS_TO_TICKS(100));
  }
  String options;
  if (g_setupLock && xSemaphoreTake(g_setupLock, pdMS_TO_TICKS(500)) == pdTRUE) {
    options = g_setupOptions;
    xSemaphoreGive(g_setupLock);
  }
  httpd_resp_set_type(req, "text/html; charset=utf-8");
  httpd_resp_send_chunk(req, SETUP_PAGE_HEAD, HTTPD_RESP_USE_STRLEN);
  if (options.length()) httpd_resp_send_chunk(req, options.c_str(), options.length());
  httpd_resp_send_chunk(req, SETUP_PAGE_TAIL, HTTPD_RESP_USE_STRLEN);
  httpd_resp_send_chunk(req, NULL, 0);
  return ESP_OK;
}

static esp_err_t setupPost(httpd_req_t* req) {
  // اسم ٣٢ وكلمة سر ٦٤، كلهن مرمّزات بالنسبة = ٢٩٠ وشوي.
  char body[320];
  int total = req->content_len;
  if (total <= 0 || total >= (int)sizeof(body)) {
    return setupReply(req, "Too long", "That did not fit. Try a shorter name.",
                      "طويل كتير", "ما زبط. جرّب اسم أقصر.");
  }
  int got = 0;
  while (got < total) {
    int r = httpd_req_recv(req, body + got, total - got);
    if (r <= 0) return setupReply(req, "Interrupted", "The form did not arrive whole.",
                                  "انقطع", "الطلب ما وصل كامل. جرّب كمان مرة.");
    got += r;
  }
  body[got] = '\0';

  if (g_roomWifiPending) {
    return setupReply(req, "Still trying", "It is still testing the network you sent.",
                      "لسا عم تجرّب", "لسا عم تجرّب الشبكة اللي بعتها. استنّى ترجع هالصفحة.");
  }
  String form(body);
  if (!roomQueueWifi(setupFormField(form, "ssid"), setupFormField(form, "pass"))) {
    return setupReply(req, "Not accepted",
                      "Pick a network name; a password is empty or 8 to 64 characters.",
                      "مش مقبول", "اختار اسم شبكة؛ كلمة السر فاضية أو من تمانية لأربعة وستين.");
  }
  // الرد قبل ما يتحرّك الراديو: التبديل بيقطع الشبكة اللي الصفحة عليها.
  return setupReply(req, "Connecting…",
                    "If it works, this network disappears and the node is back on yours. "
                    "If not, this page comes back in under a minute.",
                    "عم تتصل…",
                    "إذا زبطت، هالشبكة بتختفي والعقدة بترجع ع شبكتك. وإذا لأ، "
                    "بترجع هالصفحة بأقل من دقيقة.");
}

// المسح بيحجز ثانيتين تلاتة؛ من الحلقة بس. محاولة الاتصال الشغّالة بتفشّله: بنوقفها وبنعيد مرّة.
static void setupScan() {
  g_roomWifiHold = true;
  WiFi.disconnect(false, false);
  feedWatchdog();
  int n = WiFi.scanNetworks(false, false);
  if (n < 0) {
    delay(300);
    feedWatchdog();
    n = WiFi.scanNetworks(false, false);
  }
  g_roomWifiHold = false;
  Serial.printf("[SETUP] المسح: %d شبكة\n", n);
  String opts;
  for (int i = 0; i < n && i < 20; i++) {
    String ssid = WiFi.SSID(i);
    if (!ssid.length()) continue;
    // أسماء الشبكات بيكتبها أي حدا: بتنهرب.
    opts += "<option value=\"" + setupHtmlEscape(ssid) + "\">";
  }
  WiFi.scanDelete();
  if (g_setupLock && xSemaphoreTake(g_setupLock, pdMS_TO_TICKS(500)) == pdTRUE) {
    g_setupOptions = opts;
    xSemaphoreGive(g_setupLock);
  }
  g_setupScanGen++;
}

// الخادم قبل الراديو: شبكة بلا صفحة ما حدا بيقدر يستعملها.
static void setupStart(bool forServer) {
  if (!g_setupLock) g_setupLock = xSemaphoreCreateMutex();
  httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
  cfg.server_port = 80;
  cfg.lru_purge_enable = true;
  cfg.stack_size = 6144;
  if (httpd_start(&g_setupHttpd, &cfg) != ESP_OK) {
    Serial.println("[SETUP] المنفذ مشغول — بنرجع نجرّب");
    g_setupHttpd = NULL;
    return;
  }
  httpd_uri_t root = {};
  root.uri = "/";      root.method = HTTP_GET;  root.handler = setupRootGet;
  httpd_register_uri_handler(g_setupHttpd, &root);
  httpd_uri_t post = {};
  post.uri = "/setup"; post.method = HTTP_POST; post.handler = setupPost;
  httpd_register_uri_handler(g_setupHttpd, &post);

  // الاسم بآخر أربع خانات (أي حدا قريب بيقرا اسم الشبكة)، وكلمة السر بالكود كامل.
  String code = g_id.pair.length() ? g_id.pair : String("0000");
  String ssid = "Sandy-Room-" + (code.length() > 4 ? code.substring(code.length() - 4) : code);
  String pass = "sandy" + code;
  if (pass.length() < 8) pass = "sandysetup";

  WiFi.mode(WIFI_AP_STA);   // الطرف العادي ضروري للمسح ولتجربة الشبكة المختارة
  if (!WiFi.softAP(ssid.c_str(), pass.c_str(), 1, 0, 2)) {
    Serial.println("[SETUP] ما قدرنا نطلّع الشبكة الاحتياطية");
    httpd_stop(g_setupHttpd);
    g_setupHttpd = NULL;
    WiFi.mode(WIFI_STA);
    return;
  }
  g_setupActive = true;
  g_setupForServer = forServer;
  setupScan();
  // كلمة السر مش بالسجل.
  Serial.printf("[SETUP] ادخل ع '%s' وافتح http://192.168.4.1\n", ssid.c_str());
}

static void setupStop() {
  if (g_setupHttpd) { httpd_stop(g_setupHttpd); g_setupHttpd = NULL; }
  WiFi.softAPdisconnect(true);
  WiFi.mode(WIFI_STA);
  g_setupActive = false;
  g_setupForServer = false;
  if (g_setupLock && xSemaphoreTake(g_setupLock, pdMS_TO_TICKS(500)) == pdTRUE) {
    g_setupOptions = "";
    xSemaphoreGive(g_setupLock);
  }
  Serial.println("[SETUP] الشبكة والوسيط رجعوا — صفحة الإعداد سكّرت");
}

void roomSetupTick() {
  // الصفحة انفتحت: مسح هلّق، بلا ما نقاطع تبديل.
  if (g_setupActive && g_setupScanWanted && !g_roomWifiPending) {
    g_setupScanWanted = false;
    setupScan();
  }
  unsigned long now = millis();
  if (now - g_setupLastTickMs < ROOM_SETUP_TICK_MS) return;
  g_setupLastTickMs = now;

  if (WiFi.status() == WL_CONNECTED) {
    g_setupLastOnlineMs = now;
    if (g_mqtt.connected()) g_setupLastServerMs = now;
    unsigned long quiet = now - g_setupLastServerMs;
    if (g_setupActive) {
      // طالعة لأنه ما في شبكة: الشبكة رجعت. لأنه ما في وسيط: أول ردّ منه.
      if (!g_setupForServer || quiet < ROOM_SETUP_PROBE_MS) {
        setupStop();
      } else if (now - g_setupLastProbeMs >= ROOM_SETUP_PROBE_MS) {
        g_setupLastProbeMs = now;
        if (roomBrokerReachable()) { g_setupLastServerMs = now; setupStop(); }
      }
    } else if (quiet >= ROOM_SETUP_NO_SERVER_MS && now - g_setupLastProbeMs >= ROOM_SETUP_PROBE_MS) {
      g_setupLastProbeMs = now;
      if (roomBrokerReachable()) {
        g_setupLastServerMs = now;
      } else {
        Serial.println("[SETUP] الشبكة شغّالة بس الوسيط ما بيرد من عشر دقايق — صفحة الإعداد");
        setupStart(true);
      }
    }
    return;
  }
  if (g_setupActive) return;
  // بلا شبكة محفوظة ما في شي نستنّاه.
  if (roomSsid()[0] && now - g_setupLastOnlineMs < ROOM_SETUP_WINDOW_MS) return;
  setupStart(false);
}
