// =========================
// ESP32-CAM — Sandy's Vision (MQTT-based)
// =========================
//   • WiFi مباشر
//   • MQTT (HiveMQ) — نفس البروكر تبع Sandy
//   • Topics:
//       sandy/cam/request   ← Sandy تطلب snapshot
//       sandy/cam/snapshot  ← ESP-CAM ينشر chunks الصورة
//       sandy/cam/status    ← حالة الكاميرا كل 10s
//       sandy/cam/event     ← أحداث (e.g. capture errors)
//   • OTA + Telnet — لا حاجة لـ TTL بعد الآن
//
// التقسيم على ملفات .ino — يدمجها Arduino IDE تلقائياً:
//   esp32cam_Camera.ino — globals + setup + loop (هذا الملف)
//   cam_capture.ino     — esp_camera init + JPEG capture + chunked publish
//   cam_mqtt.ino        — MQTT connect / subscribe / status / send chunks
//   cam_ota.ino         — OTA + Telnet
//   cam_wifi.ino        — WiFi + diagnostics

#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <ArduinoOTA.h>
#include <PubSubClient.h>
#include "esp_system.h"
#include "config.h"
#include "secrets.h"

// ── Telnet mirror (Serial → WiFi) ───────────────────────────────
WiFiServer g_telnetServer(23);
WiFiClient g_telnetClient;

class MirrorStream : public Print {
 public:
  size_t write(uint8_t c) override {
    Serial.write(c);
    if (g_telnetClient && g_telnetClient.connected()) g_telnetClient.write(c);
    return 1;
  }
  size_t write(const uint8_t* buf, size_t n) override {
    Serial.write(buf, n);
    if (g_telnetClient && g_telnetClient.connected()) g_telnetClient.write(buf, n);
    return n;
  }
};
MirrorStream g_log;

// ── Cross-file state ────────────────────────────────────────────
// كل متغيّر بيستعمله أكتر من ملف لازم يكون هون: Arduino بيلزق ملفات الـino
// ورا بعض أبجدياً بعد الملف الرئيسي، فاللي هون بيسبق الكل.
void mqttPublishEvent(const char* json);
void flashSet(uint8_t level, unsigned long autoOffMs);
void flashOff();

bool g_networkServicesStarted = false;
bool g_cameraReady = false;
bool g_snapshotPending = false;          // طلب snapshot قيد التنفيذ
String g_currentRequestId = "";          // UUID من Sandy backend
unsigned long g_lastStatusPubMs = 0;

// الفلاش
FlashMode g_flashMode  = FLASH_MODE_AUTO;   // الوضع الافتراضي وقت الالتقاط
uint8_t   g_flashLevel = FLASH_DEFAULT_LEVEL;

// اللقطة الحالية والسلسلة (البانوراما)
unsigned int  g_snapshotSettleMs = 0;       // انتظار ثبات الصورة بعد حركة الرقبة
FlashMode     g_snapshotFlash = FLASH_MODE_AUTO;
unsigned int  g_burstRemaining = 0;
unsigned long g_burstIntervalMs = 800;
unsigned long g_burstNextAtMs = 0;
String        g_burstBaseId = "";
unsigned int  g_burstIndex = 0;

// آخر مرّة قلع فيها اللوح — ليش؟
//
// اللوح بيعرف السبب، وكان بيرميه. «بتعمل ريستارت» كانت سؤالًا بلا جواب لأيام،
// والجواب محفوظ برجستر بيتقرا بسطر واحد.
//
// والفرق بين الأسباب مش تفصيل — كل واحد إله حلّ تاني تمامًا:
//   انهيار كهربا  → مزوّد ومكثّف. مش كود، ولا سطر بيصلحه.
//   حارس المهام   → الكود علّق. كود.
//   انهيار برمجي  → خلل بالكود.
//   إعادة برمجية  → طلبناها إحنا. مش عطل أصلًا.
static esp_reset_reason_t g_bootReason = ESP_RST_UNKNOWN;

// بتنقرا من `cam_mqtt.ino` عشان تنحطّ بالنبضة — أردوينو بيلزق الملفات ورا
// بعض، فاللي هون بيسبق الكل والدالة بتوصلهم.
esp_reset_reason_t camBootReason() { return g_bootReason; }

static const char* bootReasonText(esp_reset_reason_t r) {
  switch (r) {
    case ESP_RST_POWERON:  return "كهربا انفصلت ورجعت";
    case ESP_RST_SW:       return "إعادة برمجية مطلوبة";
    case ESP_RST_PANIC:    return "انهيار بالكود";
    case ESP_RST_INT_WDT:  return "حارس المقاطعات";
    case ESP_RST_TASK_WDT: return "حارس المهام — إشي علّق";
    case ESP_RST_WDT:      return "حارس";
    case ESP_RST_BROWNOUT: return "انهيار كهربا — الفولت نزل";
    case ESP_RST_DEEPSLEEP: return "خروج من نوم عميق";
    case ESP_RST_EXT:      return "إعادة من الطرف الخارجي";
    default:               return "غير معروف";
  }
}

void setup() {
  Serial.begin(CAMERA_SERIAL_BAUD);
  delay(CAMERA_BOOT_DELAY_MS);
  Serial.println("\n[BOOT] ESP32-CAM starting  build=v4-capabilities");

  g_bootReason = esp_reset_reason();
  Serial.printf("[BOOT] سبب آخر إقلاع: %s (%d)\n",
                bootReasonText(g_bootReason), (int)g_bootReason);

  settingsInit();
  flashInit();

  // **بعد انهيار كهربا، ما منشغّل الفلاش.**
  //
  // الفلاش هو أكبر سحب تيّار باللوح، وبيشتغل بنفس اللحظة اللي بيصوّر فيها
  // المستشعر ويبعت الراديو — يعني تلات أحمال ع نطّة وحدة. لو المزوّد ما
  // بيتحمّلها، الفولت بينزل واللوح بيعيد التشغيل، **وبيرجع يعيدها بالالتقاط
  // اللي بعده**: حلقة بتبيّن كأنّ الروبوت خربان وهي كهربا مش كافية.
  //
  // فبنقطع الحلقة: أول التقاط بعد الانهيار بيصير بلا فلاش. صورة أعتم أحسن من
  // لوح بيختفي، والمالك بيقرا السبب بالسجل بدل ما يخمّن.
  if (g_bootReason == ESP_RST_BROWNOUT) {
    g_flashMode = FLASH_MODE_OFF;
    Serial.println("[BOOT] ⚠️ الفلاش متوقّف مؤقّتًا — آخر إقلاع كان انهيار كهربا. "
                   "بدّه مزوّد خمس فولت بأمبيرين ومكثّف ألف ميكرو.");
  }

  // ومضة إقلاع: تثبت إنّ الفلاش موصول وشغّال بلا ما نستنى الوسيط، وبتعطي
  // إشارة بصرية إنّ اللوحة قلعت من جديد.
  //
  // وبتنشال بعد انهيار كهربا: ومضة بأول ثانية من عمر لوح ما زال مزوّده ضعيف
  // بترجّعه لنفس الحفرة قبل ما يوصل الشبكة أصلًا.
  if (g_bootReason != ESP_RST_BROWNOUT) {
    flashSet(FLASH_DEFAULT_LEVEL, 250);
    delay(250);
    flashOff();
  }

  WiFi.onEvent(onWiFiEvent);
  connectWiFi();

  // ابدأ تهيئة الكاميرا — لو فشل، نعيد عند أول طلب snapshot
  setupCamera();

  // الإعدادات المحفوظة بترجع بعد ما يجهز المستشعر
  if (g_cameraReady) settingsLoadFromNvs();

  // المصافحة المشفّرة مع الوسيط بدها كتلة ذاكرة متّصلة كبيرة. لو الذاكرة ضيقة
  // بتعلّق بلا رسالة خطأ، فمنطبع القياس هون عشان يبان السبب فوراً.
  Serial.printf("[MEM] psram=%s free=%u largest_block=%u\n",
                psramFound() ? "yes" : "no",
                ESP.getFreeHeap(),
                heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
}

void loop() {
  ensureWiFiConnected();
  startNetworkServicesIfReady();

  if (g_networkServicesStarted) {
    ArduinoOTA.handle();
    updateTelnet();
    updateMQTT();
    camHttpTick();
  }

  // بعد الخدمات: التبديل بيقطع الشبكة بقصد، فلازم يصير والخدمات عارفة حالها
  // مش وهي بتتأسّس.
  camWifiTick();

  flashTick();

  // طلب snapshot في انتظار المعالجة — نلتقطه وننشره
  if (g_snapshotPending) {
    g_snapshotPending = false;
    Serial.printf("[LOOP] dispatching capture for id=%s\n", g_currentRequestId.c_str());
    Serial.flush();
    captureAndPublishSnapshot(g_currentRequestId, g_snapshotSettleMs, g_snapshotFlash);
    Serial.println("[LOOP] capture call returned");
    Serial.flush();
  }

  // سلسلة لقطات: لقطة كل فترة. الدماغ بيلف الرقبة بين الوحدة والتانية،
  // فبتطلع بانوراما بلقطات مرقّمة بنفس المعرّف.
  if (g_burstRemaining > 0 && millis() >= g_burstNextAtMs) {
    String frameId = g_burstBaseId + "-" + String(g_burstIndex);
    captureAndPublishSnapshot(frameId, g_snapshotSettleMs, g_snapshotFlash);
    g_burstIndex++;
    g_burstRemaining--;
    g_burstNextAtMs = millis() + g_burstIntervalMs;
    if (g_burstRemaining == 0) {
      char done[140];
      snprintf(done, sizeof(done),
               "{\"id\":\"%s\",\"event\":\"burst_complete\",\"frames\":%u}",
               g_burstBaseId.c_str(), g_burstIndex);
      mqttPublishEvent(done);
    }
  }

  delay(1);  // yield للـ TCP/WiFi stacks
}
