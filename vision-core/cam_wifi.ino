// =========================
// ESP32-CAM — WiFi + Diagnostics
// =========================

static unsigned long g_lastWifiAttemptMs = 0;
static uint32_t      g_wifiDropCount     = 0;

// ── الشبكة المحفوظة ─────────────────────────────────────────────────────────
//
// **الخطر اللي هالتصميم موجود عشانه:** الطريقة الوحيدة اللي بنوصل فيها للكاميرا
// هي الشبكة اللي هي عليها. كلمة سر غلط بتقطعها، وبتقطع معها القناة اللي كنّا رح
// نقولها فيها «ارجعي» — وساعتها ما إلها حل غير كبل وحرق. بسبب حرف.
//
// فبنجرّب الجديدة، وإذا ما طلعت عليها خلال المهلة، **بترجع للقديمة لحالها**.
// والقديمة ما بتنمسح إلا بعد ما الجديدة تشتغل فعلًا.
//
// وفي حارس إقلاع: علامة «قيد التجربة» بتنمسح مع كل تشغيل. يعني حتى لو انقطعت
// الكهربا بنص التجربة، الكاميرا بترجع تشتغل ع الشبكة اللي كانت عليها.
//
// نفس منطق الدماغ بالضبط (`sandy_wifi.c`) — لوحان بسلوكين مختلفين بنفس الميزة
// بيخلّوا المالك يحفظ استثناء لكل واحد.

#include <Preferences.h>

// **مساحة لحالها، مش مساحة الإعدادات.** كانت نفس `sandycam` تبع إعدادات
// المستشعر، و«رجوع للإعدادات الأصلية» بيمسح المساحة كلها — يعني بيمسح الشبكة
// كمان، والكاميرا بترجع ع شبكة المصنع وما بتوصل لحدا. تصفير الإعدادات ما لازم
// يقطع الكاميرا عن البيت.
#define WIFI_NS         "sandywifi"
#define WIFI_NS_LEGACY  "sandycam"
#define WIFI_K_SSID     "ssid"
#define WIFI_K_PASS     "pass"
#define WIFI_K_TRYING   "trying"
#define WIFI_TRY_WINDOW_MS 25000

static String g_ssid;
static String g_pass;
static bool   g_switching = false;

const char *camSsid() { return g_ssid.c_str(); }

// نقل لمرّة وحدة: الشبكة المحفوظة بالمساحة القديمة بتنتقل للجديدة، بلا ما
// المالك يعيد الإعداد بعد الترقية.
static void migrateLegacyWifi() {
  Preferences fresh;
  if (!fresh.begin(WIFI_NS, false)) return;
  bool have = fresh.getString(WIFI_K_SSID, "").length() > 0;
  if (!have) {
    Preferences old;
    if (old.begin(WIFI_NS_LEGACY, false)) {
      String s = old.getString(WIFI_K_SSID, "");
      if (s.length()) {
        fresh.putString(WIFI_K_SSID, s);
        fresh.putString(WIFI_K_PASS, old.getString(WIFI_K_PASS, ""));
        Serial.println("[WIFI] saved network moved to its own namespace");
      }
      old.remove(WIFI_K_SSID);
      old.remove(WIFI_K_PASS);
      old.remove(WIFI_K_TRYING);
      old.end();
    }
  }
  fresh.end();
}

static void loadWifiCreds() {
  g_ssid = SECRET_SSID;
  g_pass = SECRET_OPTIONAL_PASS;

  migrateLegacyWifi();
  Preferences p;
  if (!p.begin(WIFI_NS, false)) return;

  if (p.getBool(WIFI_K_TRYING, false)) {
    // انقطعت الكهربا بنص تجربة. بنمسح العلامة وبنقلع ع **آخر شبكة ثبتت** —
    // والمحفوظة هي بالزبط هاي، لأنّ الجديدة ما بتنحفظ إلا بعد ما تنجح.
    Serial.println("[WIFI] a switch was interrupted — back to the last good network");
    p.remove(WIFI_K_TRYING);
  }
  String saved = p.getString(WIFI_K_SSID, "");
  if (saved.length()) {
    g_ssid = saved;
    g_pass = p.getString(WIFI_K_PASS, "");
    Serial.printf("[WIFI] using saved network '%s'\n", g_ssid.c_str());
  }
  p.end();
}

// بتحجز لحدّ خمسة وعشرين ثانية. بتتنده من الحلقة الرئيسية، مش من رد نداء MQTT:
// رد النداء ما بيجوز ينام، وإذا نام بتتكدّس الرسائل وبيسقط الاتصال.
bool camSwitchNetwork(const String &ssid, const String &pass) {
  if (!ssid.length() || ssid.length() > 32 || pass.length() > 64) return false;
  if (g_switching) return false;
  g_switching = true;

  String oldSsid = g_ssid, oldPass = g_pass;

  Preferences p;
  if (p.begin(WIFI_NS, false)) { p.putBool(WIFI_K_TRYING, true); p.end(); }

  Serial.printf("[WIFI] trying '%s' (%d s, then back to '%s')\n",
                ssid.c_str(), WIFI_TRY_WINDOW_MS / 1000, oldSsid.c_str());

  WiFi.disconnect();
  WiFi.begin(ssid.c_str(), pass.c_str());

  // بننتظر عنوانًا، مش «اتصال»: لوح متصل وبلا عنوان ما بيوصل الخادم — يعني
  // مقطوع، بس شكله متصل.
  unsigned long t0 = millis();
  bool ok = false;
  while (millis() - t0 < WIFI_TRY_WINDOW_MS) {
    camWait(250);
    if (WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0, 0, 0, 0)) {
      ok = true;
      break;
    }
  }

  if (p.begin(WIFI_NS, false)) {
    if (ok) { p.putString(WIFI_K_SSID, ssid); p.putString(WIFI_K_PASS, pass); }
    p.remove(WIFI_K_TRYING);
    p.end();
  }

  if (ok) {
    g_ssid = ssid; g_pass = pass;
    Serial.printf("[WIFI] switched to '%s' — saved\n", g_ssid.c_str());
    g_switching = false;
    return true;
  }

  Serial.printf("[WIFI] '%s' did not come up — back to '%s'\n",
                ssid.c_str(), oldSsid.c_str());
  WiFi.disconnect();
  WiFi.begin(oldSsid.c_str(), oldPass.c_str());
  g_switching = false;
  return false;
}

void onWiFiEvent(WiFiEvent_t event, WiFiEventInfo_t info) {
  switch (event) {
    case ARDUINO_EVENT_WIFI_STA_CONNECTED:
      Serial.printf("[WIFI] connected ssid='%s'\n",
                    (char*)info.wifi_sta_connected.ssid);
      break;
    case ARDUINO_EVENT_WIFI_STA_GOT_IP:
      Serial.printf("[WIFI] got IP=%s rssi=%d\n",
                    WiFi.localIP().toString().c_str(), WiFi.RSSI());
      break;
    case ARDUINO_EVENT_WIFI_STA_DISCONNECTED:
      g_wifiDropCount++;
      Serial.printf("[WIFI] disconnected reason=%d drops=%u\n",
                    info.wifi_sta_disconnected.reason, (unsigned)g_wifiDropCount);
      break;
    default: break;
  }
}

void connectWiFi() {
  loadWifiCreds();
  Serial.printf("[WIFI] connecting to '%s' ...\n", g_ssid.c_str());
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  WiFi.begin(g_ssid.c_str(), g_pass.c_str());
}

// **تباعد متزايد، ومحاولة وحدة بكل مرّة.** كانت كل عشر ثواني تقطع وتبدأ من
// جديد، فوق إعادة الاتصال التلقائية تبع المكتبة — والاتنين بيتسابقوا، وراوتر
// بطيء (ربط + عنوان بأكتر من عشر ثواني) ما كان يلحق يكمّل ولا مرّة.
static unsigned long g_wifiRetryMs = WIFI_RECONNECT_INTERVAL_MS;
#define WIFI_RETRY_MAX_MS 60000

void ensureWiFiConnected() {
  if (WiFi.status() == WL_CONNECTED) {
    g_wifiRetryMs = WIFI_RECONNECT_INTERVAL_MS;
    return;
  }
  unsigned long now = millis();
  if (now - g_lastWifiAttemptMs < g_wifiRetryMs) return;
  g_lastWifiAttemptMs = now;
  // ما منقاطع تجربة شغّالة: هي بتقطع الاتصال بقصد وبتستنى، وإعادة الاتصال
  // التلقائية كانت بتشدّها للقديمة وتفشّلها كل مرّة.
  if (g_switching) return;
  WiFi.disconnect();
  WiFi.begin(g_ssid.c_str(), g_pass.c_str());
  g_wifiRetryMs = min(g_wifiRetryMs * 2, (unsigned long)WIFI_RETRY_MAX_MS);
}
