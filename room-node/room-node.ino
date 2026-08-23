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
// كانت `room/cmd/*` — شجرة عالمية مشتركة بين كل الزباين. يعني عقدة غرفة عند
// شخص كانت تسمع أمر «طفّي الضو» تبع شخص تاني. ومع إنّ كل لوح صار إله مفتاحه
// الخاص، **صلاحية الوسيط ما كانت تنكتب**: الدماغ بده يوصل لشجرته وللشجرة
// العامة، والخطة المجانية بتعطي صلاحية وحدة لكل مفتاح. يعني الشجرة العامة
// كانت بتكسر عزل الأجهزة وبتكلّف اشتراكًا مدفوعًا سوا.
//
// هلق كل شي تحت `sandy/node/<معرّف>/`، متل الكاميرا بالضبط — والمعرّف بينشتقّ
// من كود الاقتران المطبوع ع علبة الروبوت. عقدة الغرفة جزء من نفس الروبوت،
// فبتاخد نفس الكود.
//
//   sandy/node/<معرّف>/room/light   ← "on" | "off" | "0".."100"
//   sandy/node/<معرّف>/room/music   ← "play:F:T" | "F:T" | "vol:0..30" | "stop|…"
//   sandy/node/<معرّف>/room/color   ← (لاحقاً، لما نركّب شريط الألوان)
//   sandy/node/<معرّف>/room/status  → JSON heartbeat كل 5 ثواني
//
// رفع OTA: بعد أول فلاش بالكيبل، تظهر اللوحة كـ Network Port باسم "sandy-room".

#include <Arduino.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <ArduinoOTA.h>
#include <PubSubClient.h>
#include <ESP32Servo.h>
#include "secrets.h"

// ===== إعدادات تعايرها هنا =====
#define SERVO_PIN        13      // إشارة السيرفو (برتقالي)
#define LIGHT_REST_ANGLE 120     // النص: الذراع أفقي بلا كبس (مرجع الكبس)
#define LIGHT_ON_ANGLE   80      // كبسة أعلى القلّاب = تشغيل (ميلان ٤٠° فوق النص — شوط أوسع للكبس الأوثق)
#define LIGHT_OFF_ANGLE  160     // كبسة أسفل القلّاب = إطفاء (ميلان ٤٠° تحت النص — شوط أوسع للكبس الأوثق)
#define PRESS_HOLD_MS    400     // مدة الكبسة قبل فصل السيرفو
#define OTA_HOSTNAME     "sandy-room"
// اسم اللوح ونسخته — بيروحوا بكل نبضة. تلات ألواح إسبريسيف ع نفس الشبكة
// وتلات ملفات ما بتتبادل؛ العنوان لحاله ما بيقول أي لوح لقيت.
#define SANDY_ROOM_BOARD_ID   "sandy-room-node"
#define SANDY_ROOM_FW_VERSION "0.3.0"

// DFPlayer Mini (مشغّل الموسيقى) — تسلسلي 9600 على UART2
#define DF_PIN_ESP_RX     26     // ESP RX  ← وصّل DF TX
#define DF_PIN_ESP_TX     27     // ESP TX  → وصّل DF RX
#define DF_VOLUME_DEFAULT  20    // 0..30 (التشغيل العادي عبر ساندي)
#define DF_SELFTEST        1     // 1 = شغّل مجلد1/مقطع1 تلقائياً بعد الإقلاع (تأكيد العتاد)
#define DF_SELFTEST_VOLUME 18    // تجربة حاسمة: صوت واضح 3ث ثم يوقف

#define WIFI_RECONNECT_INTERVAL_MS  10000
#define MQTT_RECONNECT_INTERVAL_MS  5000
#define STATUS_POST_INTERVAL_MS     5000

// ===== globals =====
static WiFiClientSecure g_tcp;
static PubSubClient     g_mqtt(g_tcp);
static Servo            g_servo;
static HardwareSerial   g_df(2);                        // UART2 → DFPlayer
static unsigned long    g_lastWifiAttemptMs = 0;
static unsigned long    g_lastMqttAttemptMs = 0;
static unsigned long    g_lastStatusPubMs   = 0;
static bool             g_otaReady          = false;
static bool             g_dfTested          = false;    // self-test مرّة وحدة
static unsigned long    g_dfTestStopAtMs    = 0;        // وقت إيقاف self-test تلقائياً
static String           g_lightState        = "off";   // آخر حالة معروفة

// =========================
// معالِجات الأجهزة — أضف جهازك الجديد هنا
// =========================

// كبسة كاملة: يبدأ من النص → يكبس الزاوية → يرجع للنص، ثم يفصل الـPWM
// (ما يطنّ ولا يعيق المفتاح باليد). البداية من النص تضمن إنّ كل أمر حركة
// حقيقية حتى لو الزرّ بنفس الحالة — فما عاد يلزم «إطفاء ثم تشغيل».
static void pressSwitch(int angle) {
  g_servo.attach(SERVO_PIN);
  g_servo.write(LIGHT_REST_ANGLE);   // ابدأ من النص
  delay(PRESS_HOLD_MS);
  g_servo.write(angle);              // اكبس القلّاب
  delay(PRESS_HOLD_MS);
  g_servo.write(LIGHT_REST_ANGLE);   // ارجع للنص (ما يعيق الكبس اليدوي)
  delay(PRESS_HOLD_MS);
  g_servo.detach();
}

// مفتاح الإضاءة: on/off أو رقم (أي >0 = تشغيل لأن السيرفو ما يعتّم).
static void handleLight(const String& value) {
  bool on;
  if      (value == "on")  on = true;
  else if (value == "off") on = false;
  else                     on = (value.toInt() > 0);

  pressSwitch(on ? LIGHT_ON_ANGLE : LIGHT_OFF_ANGLE);
  g_lightState = on ? "on" : "off";
  Serial.printf("[LIGHT] %s\n", g_lightState.c_str());
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

static void dfSetVolume(int v)        { if (v < 0) v = 0; if (v > 30) v = 30; dfCmd(0x06, v); }
static void dfPlayFolderTrack(int fo, int tr) { dfCmd(0x0F, ((fo & 0xFF) << 8) | (tr & 0xFF)); }
static void dfStop()                  { dfCmd(0x16, 0); }
static void dfPause()                 { dfCmd(0x0E, 0); }
static void dfResume()                { dfCmd(0x0D, 0); }
static void dfNext()                  { dfCmd(0x01, 0); }
static void dfPrev()                  { dfCmd(0x02, 0); }

static void dfSetup() {
  g_df.begin(9600, SERIAL_8N1, DF_PIN_ESP_RX, DF_PIN_ESP_TX);
  delay(50);
  dfCmd(0x3F, 0);                 // استعلام/تهيئة
  delay(200);
  dfSetVolume(DF_VOLUME_DEFAULT);
  Serial.println("[DF] serial up on UART2");
}

// مشغّل الموسيقى: "play:F:T" | "F:T" | "vol:0..30" | "stop|pause|resume|next|prev"
static void handleMusic(const String& value) {
  Serial.printf("[MUSIC] %s\n", value.c_str());

  if      (value == "stop")   { dfStop();   return; }
  else if (value == "pause")  { dfPause();  return; }
  else if (value == "resume") { dfResume(); return; }
  else if (value == "next")   { dfNext();   return; }
  else if (value == "prev")   { dfPrev();   return; }

  if (value.startsWith("vol:")) { dfSetVolume(value.substring(4).toInt()); return; }

  String s = value.startsWith("play:") ? value.substring(5) : value;
  int colon = s.indexOf(':');
  if (colon > 0) {
    int fo = s.substring(0, colon).toInt();
    int tr = s.substring(colon + 1).toInt();
    if (fo > 0 && tr > 0) { dfPlayFolderTrack(fo, tr); return; }
  }
  Serial.printf("[MUSIC] صيغة غير معروفة: %s\n", value.c_str());
}

// مثال جاهز للجهاز الجاي (شريط الألوان) — فكّ التعليق ووصّله لما يجهز:
// static void handleColor(const String& value) {
//   Serial.printf("[COLOR] %s\n", value.c_str());
//   // TODO: اكتب لون الـLED strip حسب value (اسم لون أو #rrggbb)
// }

// جدول الأجهزة: **اسم المخرج** → دالة. هذا هو "مفتاح التوسعة".
//
// الاسم مجرّد من الشجرة بالقصد: الشجرة بتنبنى مرة وحدة بـ`roomBuildTopics`،
// فلو تغيّرت ما بينلزم تعديل سطر هون. الجدول القديم كان فيه المسار كامل بكل
// صف، فتغيير الشجرة كان لازم يمرّ ع كل صف — وهيك بينتنسى صف.
typedef void (*DeviceHandler)(const String& value);
struct Device { const char* name; DeviceHandler handler; };

static const Device DEVICES[] = {
  { "light", handleLight },
  { "music", handleMusic },
  // { "color", handleColor },   // ← أضف جهازاً جديداً بسطر واحد
};
static const size_t DEVICE_COUNT = sizeof(DEVICES) / sizeof(DEVICES[0]);

// =========================
// المواضيع — تحت شجرة الروبوت
// =========================

// نفس اشتقاق الكاميرا والدماغ حرفيًّا: حروف صغيرة وأرقام فقط من كود الاقتران.
// أي فرق بالاشتقاق بين لوحين معناه لوحين ع شجرتين، وهاد بيبيّن «الأمر ما وصل»
// بلا أي خطأ بأي مكان.
static String roomNodeId() {
  String out;
  const char* src = SANDY_PAIR_CODE;
  for (size_t i = 0; src[i]; i++) {
    char c = src[i];
    if (c >= 'A' && c <= 'Z') c = c - 'A' + 'a';
    if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) out += c;
  }
  return out;
}

static String g_topicBase;      // sandy/node/<معرّف>/room
static String g_topicFilter;    // sandy/node/<معرّف>/room/#
static String g_topicStatus;    // sandy/node/<معرّف>/room/status

static void roomBuildTopics() {
  g_topicBase   = "sandy/node/" + roomNodeId() + "/room";
  g_topicFilter = g_topicBase + "/#";
  g_topicStatus = g_topicBase + "/status";
  Serial.printf("[MQTT] node id = %s\n", roomNodeId().c_str());
}

// =========================
// MQTT
// =========================
static void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String value;
  value.reserve(length);
  for (unsigned int i = 0; i < length; i++) value += (char)payload[i];

  String t(topic);
  Serial.printf("[MQTT] %s = %s\n", t.c_str(), value.c_str());

  // بناخد المقطع الأخير بعد شجرتنا. الاشتراك بنجمة بيرجّعلنا نبضتنا كمان،
  // فبنتجاهلها صراحة — بلا هيك كل نبضة بتطبع «لا معالج» كل خمس ثواني.
  if (!t.startsWith(g_topicBase + "/")) {
    Serial.printf("[MQTT] موضوع برّا شجرتنا: %s\n", t.c_str());
    return;
  }
  String out = t.substring(g_topicBase.length() + 1);
  if (out == "status") return;

  for (size_t i = 0; i < DEVICE_COUNT; i++) {
    if (out == DEVICES[i].name) {
      DEVICES[i].handler(value);
      return;
    }
  }
  Serial.printf("[MQTT] لا معالج للمخرج %s\n", out.c_str());
}

static bool mqttReconnect() {
  if (g_mqtt.connected()) return true;
  unsigned long now = millis();
  if (now - g_lastMqttAttemptMs < MQTT_RECONNECT_INTERVAL_MS) return false;
  g_lastMqttAttemptMs = now;

  String clientId = "sandy-room-";
  clientId += String((uint32_t)ESP.getEfuseMac(), HEX);

  Serial.printf("[MQTT] connecting as %s ...\n", clientId.c_str());
  if (g_mqtt.connect(clientId.c_str(), SANDY_MQTT_USER, SANDY_MQTT_PASS)) {
    Serial.println("[MQTT] connected");
    g_mqtt.subscribe(g_topicFilter.c_str(), 1);
    Serial.printf("[MQTT] subscribed to %s\n", g_topicFilter.c_str());
    return true;
  }
  Serial.printf("[MQTT] connect failed rc=%d\n", g_mqtt.state());
  return false;
}

static void publishStatus() {
  if (!g_mqtt.connected()) return;
  unsigned long now = millis();
  if (now - g_lastStatusPubMs < STATUS_POST_INTERVAL_MS) return;
  g_lastStatusPubMs = now;

  // العنوان والاسم بالنبضة — نفس الحقلين تبع الدماغ والكاميرا بالضبط، فالخادم
  // بيقراهم بنفس المسار. بلاهم، «وين عقدة الغرفة؟» ما إله جواب بكل النظام:
  // الراوتر بيغيّر العنوان، واللوح ما بيقوله لحدا.
  char buf[240];
  snprintf(buf, sizeof(buf),
           "{\"uptime_s\":%lu,\"rssi\":%d,\"heap\":%u,\"light\":\"%s\","
           "\"ip\":\"%s\",\"board\":\"%s\"}",
           now / 1000, WiFi.RSSI(), ESP.getFreeHeap(), g_lightState.c_str(),
           WiFi.localIP().toString().c_str(), SANDY_ROOM_BOARD_ID);
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
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("[WIFI] connecting to '%s' ...\n", WIFI_SSID);
}

static void ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  unsigned long now = millis();
  if (now - g_lastWifiAttemptMs < WIFI_RECONNECT_INTERVAL_MS) return;
  g_lastWifiAttemptMs = now;
  WiFi.disconnect();
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

// =========================
// OTA — يبدأ بعد ما الواي فاي يجهز
// =========================
static void setupOTA() {
  ArduinoOTA.setHostname(OTA_HOSTNAME);
  ArduinoOTA.setPassword(SANDY_OTA_PASSWORD);
  ArduinoOTA.onStart([]() {
    Serial.println("[OTA] starting — detaching servo");
    g_servo.detach();
  });
  ArduinoOTA.onEnd([]()   { Serial.println("[OTA] done — rebooting"); });
  ArduinoOTA.onError([](ota_error_t e) { Serial.printf("[OTA] error %u\n", (unsigned)e); });
  ArduinoOTA.begin();
  Serial.printf("[OTA] ready as '%s' @ %s\n",
                OTA_HOSTNAME, WiFi.localIP().toString().c_str());
}

// =========================
// setup / loop
// =========================
void setup() {
  Serial.begin(115200);
  delay(200);
  Serial.println("\n[ROOM] boot");

  connectWiFi();

  g_tcp.setInsecure();   // مؤقتاً بدون verify cert (زي فيرموير الروبوت)
  // قبل أي اتصال: المواضيع لازم تكون جاهزة وقت أول محاولة اشتراك.
  roomBuildTopics();

  g_mqtt.setServer(SANDY_MQTT_HOST, SANDY_MQTT_PORT);
  g_mqtt.setCallback(mqttCallback);
  g_mqtt.setBufferSize(512);
  g_mqtt.setSocketTimeout(2);

  dfSetup();   // مشغّل الموسيقى على UART2
}

void loop() {
  ArduinoOTA.handle();

  // self-test مرّة وحدة: بعد ~6ث شغّل المجلد1/المقطع1 بصوت منخفض، ثم أوقف بعد 3ث
  if (DF_SELFTEST && !g_dfTested && millis() > 6000) {
    g_dfTested = true;
    dfSetVolume(DF_SELFTEST_VOLUME);
    delay(40);
    dfPlayFolderTrack(1, 1);
    g_dfTestStopAtMs = millis() + 3000;
    Serial.println("[DF] self-test → folder 1 / track 1 (3s)");
  }
  if (g_dfTestStopAtMs && millis() >= g_dfTestStopAtMs) {
    g_dfTestStopAtMs = 0;
    dfStop();
    Serial.println("[DF] self-test stop");
  }

  if (WiFi.status() != WL_CONNECTED) {
    ensureWiFi();
    return;
  }

  if (!g_otaReady) {   // الواي فاي صار جاهز — شغّل OTA مرة وحدة
    setupOTA();
    g_otaReady = true;
  }

  if (!g_mqtt.connected()) {
    mqttReconnect();
    return;
  }
  g_mqtt.loop();
  publishStatus();
}
