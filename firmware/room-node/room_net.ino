// Room node — الشبكة المحفوظة والتبديل المجرّب. نفس منطق الكاميرا (`vision-core/cam_wifi.ino`):
// الشبكة الجديدة بتنجرّب (عنوان، وبعده الوسيط بيرد منها) وبترجع للقديمة لو فشلت؛ علامة
// «قيد التجربة» بتنكتب قبل ما نلمس الراديو وبتنمسح مع كل إقلاع، فانقطاع كهربا بالنص بيقلع
// ع آخر شبكة ثبتت. المحفوظة بتغلب الأولى (اللي بالهويّة من الحرق بالكبل).

#define ROOM_WIFI_NS        "sandywifi"
#define ROOM_WIFI_K_SSID    "ssid"
#define ROOM_WIFI_K_PASS    "pass"
#define ROOM_WIFI_K_TRYING  "trying"
#define ROOM_WIFI_TRY_MS    25000   // للعنوان
#define ROOM_REACH_MS       20000   // بعده، للوسيط

static String g_ssid, g_pass;
static bool   g_roomSwitching = false;
// صفحة الإعداد عم تمسح: محاولة اتصال شغّالة بتفشّل المسح.
static volatile bool g_roomWifiHold = false;

// طلب من صفحة الإعداد (مهمّة تانية)؛ التبديل من الحلقة. محجوز لحدّ ما يخلص.
static volatile bool g_roomWifiPending = false;
static String g_roomWifiSsid, g_roomWifiPass;

const char* roomSsid() { return g_ssid.c_str(); }
bool roomWifiBusy() { return g_roomSwitching || g_roomWifiHold; }

void roomLoadWifi() {
  g_ssid = g_id.wifiSsid;
  g_pass = g_id.wifiPass;
  Preferences p;
  if (!p.begin(ROOM_WIFI_NS, false)) return;
  if (p.getBool(ROOM_WIFI_K_TRYING, false)) {
    Serial.println("[WIFI] تبديل انقطع بالنص — رجعنا ع آخر شبكة ثبتت");
    p.remove(ROOM_WIFI_K_TRYING);
  }
  String saved = p.getString(ROOM_WIFI_K_SSID, "");
  if (saved.length()) {
    g_ssid = saved;
    g_pass = p.getString(ROOM_WIFI_K_PASS, "");
    Serial.printf("[WIFI] الشبكة المحفوظة '%s'\n", g_ssid.c_str());
  }
  p.end();
}

// الوسيط بيرد من هالشبكة: اسمه بيتحلّ ومنفذه بياخد اتصال (بلا تشفير: الرام). بلا وسيط
// معروف (هويّة ناقصة) ما في شي نسأله.
bool roomBrokerReachable() {
  if (!g_id.mqttHost.length()) return true;
  if (WiFi.status() != WL_CONNECTED) return false;
  IPAddress ip;
  if (!WiFi.hostByName(g_id.mqttHost.c_str(), ip) || ip == IPAddress((uint32_t)0)) return false;
  WiFiClient c;
  bool ok = c.connect(ip, SANDY_MQTT_PORT, 5000);
  c.stop();
  return ok;
}

static void roomWaitFed(unsigned long ms) {
  unsigned long t0 = millis();
  while (millis() - t0 < ms) {
    feedWatchdog();
    delay(50);
  }
}

// بتحجز لحدّ ٤٥ ثانية، والحارس تلاتين: بتطعمه وهي بتستنّى. من الحلقة بس.
bool roomSwitchNetwork(const String& ssid, const String& pass) {
  if (!ssid.length() || ssid.length() > 32 || pass.length() > 64) return false;
  if (g_roomSwitching) return false;
  g_roomSwitching = true;
  String oldSsid = g_ssid, oldPass = g_pass;

  Preferences p;
  if (!p.begin(ROOM_WIFI_NS, false) || !p.putBool(ROOM_WIFI_K_TRYING, true)) {
    // بلا العلامة، انقطاع كهربا بالنص بيقلع ع شبكة ما انجرّبت.
    p.end();
    Serial.println("[WIFI] ما قدرت أكتب علامة التجربة — التبديل مرفوض");
    g_roomSwitching = false;
    return false;
  }
  p.end();
  Serial.printf("[WIFI] بجرّب '%s' (%d ث للعنوان و%d للوسيط، وبعدها رجوع لـ'%s')\n",
                ssid.c_str(), ROOM_WIFI_TRY_MS / 1000, ROOM_REACH_MS / 1000, oldSsid.c_str());
  g_mqtt.disconnect();
  WiFi.disconnect();
  WiFi.begin(ssid.c_str(), pass.c_str());

  unsigned long t0 = millis();
  bool ok = false;
  while (millis() - t0 < ROOM_WIFI_TRY_MS) {
    roomWaitFed(250);
    if (WiFi.status() == WL_CONNECTED && WiFi.localIP() != IPAddress(0, 0, 0, 0)) {
      ok = true;
      break;
    }
  }
  // عنوان مش كفاية: نقطة جوال بلا بيانات بتعطي عنوان، والعقدة بتعلق عليها.
  bool noServer = false;
  if (ok) {
    unsigned long t1 = millis();
    ok = false;
    while (millis() - t1 < ROOM_REACH_MS && WiFi.status() == WL_CONNECTED) {
      feedWatchdog();
      if (roomBrokerReachable()) { ok = true; break; }
      roomWaitFed(2000);
    }
    noServer = !ok;
  }

  if (p.begin(ROOM_WIFI_NS, false)) {
    if (ok) { p.putString(ROOM_WIFI_K_SSID, ssid); p.putString(ROOM_WIFI_K_PASS, pass); }
    p.remove(ROOM_WIFI_K_TRYING);
    p.end();
  }
  if (ok) {
    g_ssid = ssid;
    g_pass = pass;
    Serial.printf("[WIFI] انتقلنا لـ'%s' — انحفظت\n", g_ssid.c_str());
    g_roomSwitching = false;
    return true;
  }
  Serial.printf("[WIFI] '%s' %s — رجوع لـ'%s'\n", ssid.c_str(),
                noServer ? "ما في وسيط منها" : "ما اتصلت", oldSsid.c_str());
  WiFi.disconnect();
  WiFi.begin(oldSsid.c_str(), oldPass.c_str());
  g_roomSwitching = false;
  return false;
}

// من صفحة الإعداد. حدود المعيار: الاسم ≤ ٣٢ بايت، كلمة السر فاضية أو ٨..٦٤.
bool roomQueueWifi(const String& ssid, const String& pass) {
  if (ssid.length() == 0 || ssid.length() > 32 || pass.length() > 64 ||
      (pass.length() > 0 && pass.length() < 8)) {
    return false;
  }
  if (g_roomWifiPending) return false;
  g_roomWifiSsid = ssid;
  g_roomWifiPass = pass;
  g_roomWifiPending = true;   // آخر إشي: الحلقة بتقرا الاسم بعده
  return true;
}

// التبديل ع نسخة محلّية، والطلب بيضل محجوز لحدّ ما يخلص (ضغطة تانية بتنرفض).
void roomWifiTick() {
  if (!g_roomWifiPending) return;
  String ssid = g_roomWifiSsid, pass = g_roomWifiPass;
  bool ok = roomSwitchNetwork(ssid, pass);
  g_roomWifiPending = false;
  Serial.printf("[WIFI] التبديل %s\n", ok ? "زبط" : "رجع للقديمة");
}

// الاتصال الأول بالشبكة المحفوظة (أو الأولى).
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  WiFi.begin(g_ssid.c_str(), g_pass.c_str());
  g_lastWifiAttemptMs = millis();
  Serial.printf("[WIFI] connecting to '%s' ...\n", g_ssid.c_str());
}

// مهلة متضاعفة لدقيقة، عشان ما نقطع محاولة شغّالة ولا نغرق الراوتر؛ ولا تجربة ولا مسح.
void ensureWiFi() {
  if (roomWifiBusy() || !g_ssid.length()) return;
  unsigned long now = millis();
  if (now - g_lastWifiAttemptMs < g_wifiRetryMs) return;
  g_lastWifiAttemptMs = now;
  g_wifiRetryMs = min(g_wifiRetryMs * 2, (unsigned long)WIFI_RETRY_MAX_MS);
  Serial.printf("[WIFI] إعادة محاولة (الجاية بعد %lus)\n", g_wifiRetryMs / 1000UL);
  WiFi.disconnect();
  WiFi.begin(g_ssid.c_str(), g_pass.c_str());
}
