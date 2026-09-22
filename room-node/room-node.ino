// =========================
// Sandy — Room Node (الـESP32 القديمة)
// =========================
// جهاز ثانٍ على نفس بروكر HiveMQ تبع الروبوت. يشترك بمواضيع غرفته
// اللي تنشرها ساندي (العقد في cloud/app/integrations/room_device.py)
// وينفّذها على عتاد الغرفة.
//
// الفلسفة: كل جهاز بالغرفة = صف واحد بجدول DEVICES + دالة معالِجة.
// إضافة جهاز جديد (شريط ألوان، مروحة، ستارة) = أضف سطر بالجدول + دالة. خلص.
//
// أول جهاز: مفتاح الإضاءة عبر سيرفو يكبس القلّاب ميكانيكياً (صفر تلامس مع 220).
//
// ── المواضيع: تحت شجرة الروبوت، مش شجرة عامة ────────────────────────────────
//
// كانت `room/cmd/*` — شجرة عالمية مشتركة بين كل الزباين. هلق كل شي تحت
// `sandy/node/<معرّف>/`، متل الكاميرا بالضبط — والمعرّف بينشتقّ من كود الاقتران
// المطبوع ع علبة الروبوت. عقدة الغرفة جزء من نفس الروبوت، فبتاخد نفس الكود.
//
//   sandy/node/<معرّف>/room/light   ← "on" | "off" | "0".."100"
//   sandy/node/<معرّف>/room/music   ← "on|off|stop|pause|resume|next|prev"
//                                     | "play:F:T" | "vol:0..30"
//   sandy/node/<معرّف>/room/status  → نبضة كل 5 ثواني، و«متّصل/مقطوع» محفوظة
//
// ── التحديث ─────────────────────────────────────────────────────────────────
// بعد البيع: اللوح بيسأل الخادم عن نسخة موقّعة (sandy_ota_pull.h). الترقية ع
// الشبكة المحلية بنسخة التطوير بس (`SANDY_DEV`).

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ESP32Servo.h>
#include <Preferences.h>
#include "esp_task_wdt.h"
#include "secrets.h"
#include "sandy_ca_roots.h"
#include <time.h>

#ifndef SANDY_DEV
  #define SANDY_DEV 0
#endif
#if SANDY_DEV
  #include <ArduinoOTA.h>
  #ifndef SANDY_OTA_PASSWORD
    #error "SANDY_DEV needs SANDY_OTA_PASSWORD in secrets.h"
  #endif
#endif

// خادم ساندي — التحديثات بتنزل منه.
#ifndef SANDY_API_HOST
  #define SANDY_API_HOST "sandy-robot-3da0693d32f7.herokuapp.com"
#endif

// الهويّة (الكود ومفاتيح الوسيط والشبكة) بذاكرة اللوح مش بالصورة — شوف
// sandy_identity.h. هيك صورة التحديث وحدة لكل الروبوتات وما فيها ولا سرّ.
#include "sandy_identity.h"
#include "sandy_ota_pull.h"

// ===== إعدادات تعايرها هنا =====
#define SERVO_PIN        13      // إشارة السيرفو (برتقالي)
#define LIGHT_REST_ANGLE 120     // النص: الذراع أفقي بلا كبس (مرجع الكبس)
#define LIGHT_ON_ANGLE   80      // كبسة أعلى القلّاب = تشغيل
#define LIGHT_OFF_ANGLE  160     // كبسة أسفل القلّاب = إطفاء
#define PRESS_HOLD_MS    400     // مدة كل مرحلة من الكبسة
#define OTA_HOSTNAME     "sandy-room"
// اسم اللوح ونسخته — بيروحوا بكل نبضة.
#define SANDY_ROOM_BOARD_ID   "sandy-room-node"
#define SANDY_ROOM_FW_VERSION "0.4.0"

// DFPlayer Mini (مشغّل الموسيقى) — تسلسلي 9600 على UART2
#define DF_PIN_ESP_RX      26    // ESP RX  ← وصّل DF TX
#define DF_PIN_ESP_TX      27    // ESP TX  → وصّل DF RX
#define DF_VOLUME_DEFAULT  20    // 0..30
// المشغّل بياخد ثانية ونص تقريبًا بعد الكهربا لحتى يقرا الكرت. أي أمر قبلها
// بيضيع — وكان الصوت الأوّلي بيروح هيك، فأول أغنية بتطلع بصوت المصنع.
#define DF_READY_AFTER_MS  2000
#define DF_DEFAULT_FOLDER  1     // «شغّل الموسيقى» بلا شي قبلها = مجلد 1 مقطع 1
#define DF_DEFAULT_TRACK   1
#define DF_SELFTEST        0     // 1 = يشغّل مجلد1/مقطع1 تلات ثواني بعد الإقلاع (للتجربة بس)
#define DF_SELFTEST_VOLUME 18

#define WIFI_RETRY_MIN_MS           5000
#define WIFI_RETRY_MAX_MS           60000
#define MQTT_RECONNECT_INTERVAL_MS  5000
#define STATUS_POST_INTERVAL_MS     5000
// ربع ساعة بلا وسيط = إعادة تشغيل. اللوح الصغير بيعلق أحيانًا بحالة شبكة ما
// بيطلع منها لحاله، وإعادة التشغيل أرخص من زبون بيفصل الكهربا بإيده.
#define OFFLINE_REBOOT_MS           (15UL * 60UL * 1000UL)
#define ROOM_WDT_TIMEOUT_MS         30000
#define TLS_HANDSHAKE_TIMEOUT_S     10
// قبل هالتاريخ الساعة مش مضبوطة (اللوح بيقلع ع سنة سبعين) والشهادات بتنرفض.
#define CLOCK_SANE_EPOCH            1700000000L
#define ROOM_NVS                    "sandyroom"

// ===== globals =====
static WiFiClientSecure g_tcp;
static PubSubClient     g_mqtt(g_tcp);
static Servo            g_servo;
static HardwareSerial   g_df(2);                        // UART2 → DFPlayer
static unsigned long    g_lastWifiAttemptMs = 0;
static unsigned long    g_wifiRetryMs       = WIFI_RETRY_MIN_MS;
static unsigned long    g_lastMqttAttemptMs = 0;
static unsigned long    g_lastStatusPubMs   = 0;
static unsigned long    g_lastOnlineMs      = 0;
static bool             g_netServicesReady  = false;
static const char*      g_lightState        = "unknown"; // ما بنعرف لحدّ أول كبسة
static int              g_dfVolume          = DF_VOLUME_DEFAULT;
static bool             g_dfReady           = false;
static bool             g_dfPlayedSinceBoot = false;
static char             g_ntpGateway[16]    = {0};       // لازم يعيش: خدمة الوقت بتحفظ المؤشّر

static void feedWatchdog() { esp_task_wdt_reset(); }

// =========================
// الإضاءة — سيرفو بلا حجز للحلقة
// =========================
//
// **الكبسة كانت تلات `delay` ورا بعض — ثانية وربع الحلقة واقفة.** بهالوقت ما
// في وسيط ولا نبضة، وأمرين ورا بعض («طفّي، لا شغّل») كانوا بيتنفّذوا كبستين
// كاملتين. هلّق الكبسة مراحل بتمشي مع الحلقة، والأمر الجديد وقت الكبسة بيستبدل
// اللي مستني: آخر أمر هو اللي بيربح.

enum PressPhase { PRESS_IDLE, PRESS_REST, PRESS_PUSH, PRESS_BACK };
static PressPhase    g_pressPhase   = PRESS_IDLE;
static unsigned long g_pressStepMs  = 0;
static int           g_pressTarget  = -1;   // 1 = تشغيل، 0 = إطفاء
static int           g_pressPending = -1;   // أمر وصل وقت الكبسة

static void pressStart(int on) {
  g_pressTarget = on;
  g_servo.attach(SERVO_PIN);
  g_servo.write(LIGHT_REST_ANGLE);   // ابدأ من النص: كل أمر حركة حقيقية
  g_pressPhase  = PRESS_REST;
  g_pressStepMs = millis();
}

static void pressLoop() {
  if (g_pressPhase == PRESS_IDLE) {
    if (g_pressPending >= 0) {
      int next = g_pressPending;
      g_pressPending = -1;
      pressStart(next);
    }
    return;
  }
  if (millis() - g_pressStepMs < PRESS_HOLD_MS) return;
  g_pressStepMs = millis();
  switch (g_pressPhase) {
    case PRESS_REST:
      g_servo.write(g_pressTarget ? LIGHT_ON_ANGLE : LIGHT_OFF_ANGLE);
      g_pressPhase = PRESS_PUSH;
      break;
    case PRESS_PUSH:
      g_servo.write(LIGHT_REST_ANGLE);   // ارجع للنص: ما يعيق الكبس باليد
      g_pressPhase = PRESS_BACK;
      break;
    case PRESS_BACK:
      g_servo.detach();                  // بلا طنين، والمفتاح حرّ باليد
      g_lightState = g_pressTarget ? "on" : "off";
      Serial.printf("[LIGHT] %s\n", g_lightState);
      g_pressPhase = PRESS_IDLE;
      // نفس الحالة مرتين ورا بعض = كبسة وحدة بتكفي.
      if (g_pressPending == g_pressTarget) g_pressPending = -1;
      break;
    default:
      g_pressPhase = PRESS_IDLE;
  }
}

static bool parseBoundedInt(const String& s, int lo, int hi, int* out) {
  if (s.length() == 0 || s.length() > 3) return false;
  for (size_t i = 0; i < s.length(); i++) if (!isDigit(s[i])) return false;
  int v = s.toInt();
  if (v < lo || v > hi) return false;
  *out = v;
  return true;
}

// مفتاح الإضاءة: on/off أو 0..100 (أي >0 = تشغيل لأن السيرفو ما بيعتّم).
// **صارم:** «oops» كانت بتصير `toInt()==0` = «طفّي»، يعني أي كلمة غلط بتطفي الضو.
static void handleLight(const String& value) {
  int on = -1, level;
  if      (value == "on")  on = 1;
  else if (value == "off") on = 0;
  else if (parseBoundedInt(value, 0, 100, &level)) on = level > 0 ? 1 : 0;
  if (on < 0) {
    Serial.printf("[LIGHT] أمر مش مفهوم، انتجاهل: %.20s\n", value.c_str());
    return;
  }
  if (g_pressPhase == PRESS_IDLE) pressStart(on);
  else g_pressPending = on;
}

// ---- DFPlayer Mini: إطارات أوامر خام (بلا مكتبة خارجية) ----
// الإطار: 7E FF 06 CMD 00 PARAM_H PARAM_L CHK_H CHK_L EF
static void dfCmd(uint8_t cmd, uint16_t param) {
  uint8_t f[10] = { 0x7E, 0xFF, 0x06, cmd, 0x00,
                    (uint8_t)(param >> 8), (uint8_t)(param & 0xFF), 0, 0, 0xEF };
  uint16_t sum = f[1] + f[2] + f[3] + f[4] + f[5] + f[6];
  uint16_t chk = 0xFFFF - sum + 1;
  f[7] = (uint8_t)(chk >> 8);
  f[8] = (uint8_t)(chk & 0xFF);
  g_df.write(f, sizeof(f));
}

static void dfSendVolume()  { dfCmd(0x06, (uint16_t)g_dfVolume); }
static void dfStop()        { dfCmd(0x16, 0); }
static void dfPause()       { dfCmd(0x0E, 0); }
static void dfResume()      { dfCmd(0x0D, 0); }
static void dfNext()        { dfCmd(0x01, 0); }
static void dfPrev()        { dfCmd(0x02, 0); }

// الصوت قبل كل تشغيل: المشغّل بينسى صوته لو انقطعت عنه الكهربا لحظة
// (السيرفو بيسحب تيار)، والأغنية بتطلع بصوت المصنع العالي.
static void dfPlayFolderTrack(int fo, int tr) {
  dfSendVolume();
  delay(30);
  dfCmd(0x0F, (uint16_t)(((fo & 0xFF) << 8) | (tr & 0xFF)));
  g_dfPlayedSinceBoot = true;
}

static void dfSetup() {
  Preferences p;
  if (p.begin(ROOM_NVS, true)) {
    g_dfVolume = p.getUChar("vol", DF_VOLUME_DEFAULT);
    p.end();
  }
  if (g_dfVolume > 30) g_dfVolume = DF_VOLUME_DEFAULT;
  g_df.begin(9600, SERIAL_8N1, DF_PIN_ESP_RX, DF_PIN_ESP_TX);
  Serial.println("[DF] serial up on UART2");
}

static void dfLoop() {
  if (!g_dfReady && millis() >= DF_READY_AFTER_MS) {
    g_dfReady = true;
    dfSendVolume();
    Serial.printf("[DF] جاهز، الصوت %d\n", g_dfVolume);
  }
#if DF_SELFTEST
  static bool tested = false;
  static unsigned long stopAt = 0;
  if (g_dfReady && !tested && millis() > 6000) {
    tested = true;
    int keep = g_dfVolume;
    g_dfVolume = DF_SELFTEST_VOLUME;
    dfPlayFolderTrack(1, 1);
    g_dfVolume = keep;
    stopAt = millis() + 3000;
    Serial.println("[DF] self-test → folder 1 / track 1 (3s)");
  }
  if (stopAt && (long)(millis() - stopAt) >= 0) {
    stopAt = 0;
    dfStop();
    Serial.println("[DF] self-test stop");
  }
#endif
}

// مشغّل الموسيقى: "on|off|stop|pause|resume|next|prev" | "play:F:T" | "F:T" | "vol:0..30"
static void handleMusic(const String& value) {
  Serial.printf("[MUSIC] %.24s\n", value.c_str());

  // «on» و«off» هنّ كلمات المشاهد والخادم (room_device.normalize_action).
  // «on» بعد إقلاع ما شغّل شي = «كمّل» ع ولا إشي، فالمشغّل بيسكت. هيك بيشغّل
  // الافتراضي بدل ما يطنّش.
  if (value == "on") {
    if (g_dfPlayedSinceBoot) { dfSendVolume(); delay(30); dfResume(); }
    else dfPlayFolderTrack(DF_DEFAULT_FOLDER, DF_DEFAULT_TRACK);
    return;
  }
  if (value == "off" || value == "stop") { dfStop();   return; }
  if (value == "pause")                  { dfPause();  return; }
  if (value == "resume")                 { dfSendVolume(); delay(30); dfResume(); return; }
  if (value == "next")                   { dfNext();   return; }
  if (value == "prev")                   { dfPrev();   return; }

  if (value.startsWith("vol:")) {
    int v;
    if (!parseBoundedInt(value.substring(4), 0, 30, &v)) {
      Serial.println("[MUSIC] صوت برّا المدى، انتجاهل");
      return;
    }
    g_dfVolume = v;
    dfSendVolume();
    Preferences p;
    if (p.begin(ROOM_NVS, false)) { p.putUChar("vol", (uint8_t)v); p.end(); }
    return;
  }

  String s = value.startsWith("play:") ? value.substring(5) : value;
  int colon = s.indexOf(':');
  int fo, tr;
  if (colon > 0 && parseBoundedInt(s.substring(0, colon), 1, 99, &fo) &&
      parseBoundedInt(s.substring(colon + 1), 1, 255, &tr)) {
    dfPlayFolderTrack(fo, tr);
    return;
  }
  Serial.printf("[MUSIC] صيغة غير معروفة: %.24s\n", value.c_str());
}

// جدول الأجهزة: **اسم المخرج** → دالة. هذا هو "مفتاح التوسعة".
// والنبضة بتعلن نفس الأسماء (`outputs`)، والخادم ما بيبعت إلا لمخرج مُعلَن.
typedef void (*DeviceHandler)(const String& value);
struct Device { const char* name; const char* kind; DeviceHandler handler; };

static const Device DEVICES[] = {
  // `kind` لازم يكون من قائمة الخادم (`KNOWN_CAPABILITIES` بـ node_store) —
  // نوع خارجها بينرفض بصمت والجهاز ما بيظهر بالتطبيق.
  { "light", "relay", handleLight },
  { "music", "audio", handleMusic },
};
static const size_t DEVICE_COUNT = sizeof(DEVICES) / sizeof(DEVICES[0]);

// =========================
// المواضيع — تحت شجرة الروبوت
// =========================

// نفس اشتقاق الكاميرا والدماغ حرفيًّا: حروف صغيرة وأرقام فقط من كود الاقتران.
static String roomNodeId() {
  String out;
  const char* src = g_id.pair.c_str();
  for (size_t i = 0; src[i]; i++) {
    char c = src[i];
    if (c >= 'A' && c <= 'Z') c = c - 'A' + 'a';
    if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) out += c;
  }
  return out;
}

static String g_nodeId;
static String g_topicBase;      // sandy/node/<معرّف>/room
static String g_topicStatus;    // sandy/node/<معرّف>/room/status
static String g_clientId;

static void roomBuildTopics() {
  g_nodeId      = roomNodeId();
  g_topicBase   = "sandy/node/" + g_nodeId + "/room";
  g_topicStatus = g_topicBase + "/status";
  // المعرّف بالوسيط: العقدة + العنوان الكامل. كان نص العنوان بس (٣٢ بت)، ولوحين
  // بنفس النص بيطردوا بعض من الوسيط كل خمس ثواني.
  uint64_t mac = ESP.getEfuseMac();
  char macHex[13];
  snprintf(macHex, sizeof(macHex), "%04x%08x",
           (unsigned)((mac >> 32) & 0xFFFF), (unsigned)(mac & 0xFFFFFFFF));
  g_clientId = "sandy-room-" + g_nodeId + "-" + macHex;
  Serial.printf("[MQTT] node id = %s\n", g_nodeId.c_str());
}

// =========================
// MQTT
// =========================
static void mqttCallback(char* topic, byte* payload, unsigned int length) {
  if (length > 64) {
    Serial.printf("[MQTT] رسالة أطول من اللازم (%u) — انتجاهلت\n", length);
    return;
  }
  String value;
  value.reserve(length);
  for (unsigned int i = 0; i < length; i++) value += (char)payload[i];
  value.trim();

  String t(topic);
  if (!t.startsWith(g_topicBase + "/")) return;
  String out = t.substring(g_topicBase.length() + 1);
  for (size_t i = 0; i < DEVICE_COUNT; i++) {
    if (out == DEVICES[i].name) {
      DEVICES[i].handler(value);
      return;
    }
  }
  Serial.printf("[MQTT] لا معالج للمخرج %.16s\n", out.c_str());
}

static bool mqttReconnect() {
  unsigned long now = millis();
  if (now - g_lastMqttAttemptMs < MQTT_RECONNECT_INTERVAL_MS) return false;
  g_lastMqttAttemptMs = now;

  // التحقّق من الشهادة بيقارن تاريخها بساعة اللوح، فبنستنى الساعة.
  if (time(nullptr) < CLOCK_SANE_EPOCH) {
    Serial.println("[MQTT] الساعة لسا مش مضبوطة — بستنى قبل الاتصال");
    return false;
  }

  Serial.printf("[MQTT] connecting as %s ...\n", g_clientId.c_str());
  // الوصيّة: لو انقطعنا بلا وداع، الوسيط بينشر «مقطوع» محفوظة ع موضوع الحالة،
  // والتطبيق بيعرف فورًا بدل ما يستنى النبضات تبطّل.
  if (!g_mqtt.connect(g_clientId.c_str(), g_id.mqttUser.c_str(), g_id.mqttPass.c_str(),
                      g_topicStatus.c_str(), 1, true, "{\"online\":false}")) {
    Serial.printf("[MQTT] connect failed rc=%d\n", g_mqtt.state());
    return false;
  }
  // كل مخرج بموضوعه بالضبط — مش نجمة بترجّعلنا نبضاتنا وأي إشي بينكتب تحتنا.
  bool ok = true;
  for (size_t i = 0; i < DEVICE_COUNT; i++) {
    String topic = g_topicBase + "/" + DEVICES[i].name;
    if (!g_mqtt.subscribe(topic.c_str(), 1)) {
      Serial.printf("[MQTT] الاشتراك فشل: %s\n", topic.c_str());
      ok = false;
    }
  }
  if (!ok) {
    // اتصال بلا اشتراك = لوح بيبيّن شغّال وما بيسمع. أحسن نعيد من الأول.
    g_mqtt.disconnect();
    return false;
  }
  g_mqtt.publish(g_topicStatus.c_str(), "{\"online\":true}", true);
  Serial.println("[MQTT] connected + subscribed");
  g_lastStatusPubMs = 0;   // نبضة كاملة فورًا
  return true;
}

static void publishStatus() {
  unsigned long now = millis();
  if (g_lastStatusPubMs && now - g_lastStatusPubMs < STATUS_POST_INTERVAL_MS) return;
  g_lastStatusPubMs = now ? now : 1;

  // **`outputs` هي اللي بتخلّي الغرفة تظهر بالتطبيق**، وهي نفس جدول `DEVICES`.
  char outputs[160];
  size_t used = 0;
  outputs[0] = '\0';
  for (size_t i = 0; i < DEVICE_COUNT && used < sizeof(outputs); i++) {
    int n = snprintf(outputs + used, sizeof(outputs) - used,
                     "%s{\"id\":\"%s\",\"kind\":\"%s\"}", i ? "," : "",
                     DEVICES[i].name, DEVICES[i].kind);
    if (n < 0 || (size_t)n >= sizeof(outputs) - used) {
      Serial.println("[STATUS] قائمة المخارج أطول من المخزن");
      return;
    }
    used += (size_t)n;
  }

  char buf[400];
  int n = snprintf(buf, sizeof(buf),
                   "{\"online\":true,\"uptime_s\":%lu,\"rssi\":%d,\"heap\":%u,"
                   "\"light\":\"%s\",\"ip\":\"%s\",\"board\":\"%s\",\"fw\":\"%s\","
                   "\"outputs\":[%s]}",
                   now / 1000UL, (int)WiFi.RSSI(), (unsigned)ESP.getFreeHeap(),
                   g_lightState, WiFi.localIP().toString().c_str(),
                   SANDY_ROOM_BOARD_ID, SANDY_ROOM_FW_VERSION, outputs);
  // نبضة مقطوعة = JSON مكسور = الخادم بيرميها بصمت والغرفة بتختفي من التطبيق.
  if (n < 0 || (size_t)n >= sizeof(buf)) {
    Serial.println("[STATUS] النبضة أطول من المخزن — ما انبعتت");
    return;
  }
  g_mqtt.publish(g_topicStatus.c_str(), buf, false);
}

// =========================
// WiFi
// =========================
static void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.setSleep(false);
  WiFi.setAutoReconnect(true);
  WiFi.persistent(false);
  WiFi.begin(g_id.wifiSsid.c_str(), g_id.wifiPass.c_str());
  g_lastWifiAttemptMs = millis();
  Serial.printf("[WIFI] connecting to '%s' ...\n", g_id.wifiSsid.c_str());
}

// المحاولة كل عشر ثواني للأبد كانت بتقطع محاولة الراوتر الحالية قبل ما تخلص،
// وبتغرق راوتر عم يقلع. هلّق المهلة بتتضاعف لدقيقة.
static void ensureWiFi() {
  unsigned long now = millis();
  if (now - g_lastWifiAttemptMs < g_wifiRetryMs) return;
  g_lastWifiAttemptMs = now;
  g_wifiRetryMs = min(g_wifiRetryMs * 2, (unsigned long)WIFI_RETRY_MAX_MS);
  Serial.printf("[WIFI] إعادة محاولة (الجاية بعد %lus)\n", g_wifiRetryMs / 1000UL);
  WiFi.disconnect();
  WiFi.begin(g_id.wifiSsid.c_str(), g_id.wifiPass.c_str());
}

// الوقت: الراوتر كمان مصدر. شبكات كتير بتسدّ خوادم الوقت العامة، وبلا ساعة
// ما في شهادة بتنقبل وما في وسيط.
static void startClock() {
  String gw = WiFi.gatewayIP().toString();
  strncpy(g_ntpGateway, gw.c_str(), sizeof(g_ntpGateway) - 1);
  configTime(0, 0, "pool.ntp.org", "time.google.com", g_ntpGateway);
}

#if SANDY_DEV
static void setupLanOta() {
  ArduinoOTA.setHostname(OTA_HOSTNAME);
  ArduinoOTA.setPassword(SANDY_OTA_PASSWORD);
  ArduinoOTA.onStart([]() {
    Serial.println("[OTA] starting — detaching servo");
    g_servo.detach();
  });
  ArduinoOTA.onEnd([]()   { Serial.println("[OTA] done — rebooting"); });
  ArduinoOTA.onError([](ota_error_t e) { Serial.printf("[OTA] error %u\n", (unsigned)e); });
  ArduinoOTA.begin();
  Serial.printf("[OTA] LAN ready as '%s' @ %s\n",
                OTA_HOSTNAME, WiFi.localIP().toString().c_str());
}
#endif

static bool roomIdle() { return g_pressPhase == PRESS_IDLE && g_pressPending < 0; }

// =========================
// setup / loop
// =========================
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.printf("\n[ROOM] boot — %s %s\n", SANDY_ROOM_BOARD_ID, SANDY_ROOM_FW_VERSION);

  // المراقب: حلقة علقت نص دقيقة = إعادة تشغيل، بدل لوح ميّت بينبض وما بيسمع.
  esp_task_wdt_config_t wdt = {
    .timeout_ms = ROOM_WDT_TIMEOUT_MS,
    .idle_core_mask = 0,
    .trigger_panic = true,
  };
  if (esp_task_wdt_reconfigure(&wdt) != ESP_OK) esp_task_wdt_init(&wdt);
  esp_task_wdt_add(nullptr);

  sandyIdentityLoad(SANDY_PAIR_CODE, SANDY_MQTT_HOST, SANDY_MQTT_USER, SANDY_MQTT_PASS, nullptr,
                    WIFI_SSID, WIFI_PASSWORD);
  roomBuildTopics();
  dfSetup();
  if (g_id.wifiSsid.length()) connectWiFi();

  // بنتحقّق من شهادة الوسيط. بلاها، أي حدا ع نفس الشبكة بيعمل حاله الوسيط.
  g_tcp.setCACert(SANDY_CA_ROOTS);
  g_tcp.setHandshakeTimeout(TLS_HANDSHAKE_TIMEOUT_S);
  g_tcp.setTimeout(TLS_HANDSHAKE_TIMEOUT_S * 1000);
  g_mqtt.setServer(g_id.mqttHost.c_str(), SANDY_MQTT_PORT);
  g_mqtt.setCallback(mqttCallback);
  g_mqtt.setBufferSize(512);
  g_mqtt.setSocketTimeout(TLS_HANDSHAKE_TIMEOUT_S);

  static SandyOtaConfig ota;
  static String deviceId = "room-" + g_nodeId;
  ota.board    = "room";
  ota.host     = SANDY_API_HOST;
  ota.deviceId = deviceId.c_str();
  ota.version  = SANDY_ROOM_FW_VERSION;
  ota.caRoots  = SANDY_CA_ROOTS;
  ota.idle     = roomIdle;
  ota.prepare  = []() { g_mqtt.disconnect(); };
  ota.feed     = feedWatchdog;
  sandyOtaBegin(ota);

  g_lastOnlineMs = millis();
}

void loop() {
  feedWatchdog();
  pressLoop();
  dfLoop();

  bool online = false;
  if (!g_id.complete() || !g_id.wifiSsid.length()) {
    // بلا هويّة ما في وين نروح. الموسيقى والمفتاح المحلي بيضلّوا شغّالين.
  } else if (WiFi.status() != WL_CONNECTED) {
    g_netServicesReady = false;
    ensureWiFi();
  } else {
    g_wifiRetryMs = WIFI_RETRY_MIN_MS;
    if (!g_netServicesReady) {
      startClock();
#if SANDY_DEV
      setupLanOta();
#endif
      g_netServicesReady = true;
    }
#if SANDY_DEV
    ArduinoOTA.handle();
#endif
    if (g_mqtt.connected() || mqttReconnect()) {
      g_mqtt.loop();
      publishStatus();
      online = g_mqtt.connected();
    }
  }

  if (online) g_lastOnlineMs = millis();
  else if (g_id.complete() && millis() - g_lastOnlineMs > OFFLINE_REBOOT_MS && roomIdle()) {
    Serial.println("[ROOM] ربع ساعة بلا وسيط — إعادة تشغيل");
    delay(100);
    ESP.restart();
  }

  sandyOtaLoop(online);
  delay(5);
}
