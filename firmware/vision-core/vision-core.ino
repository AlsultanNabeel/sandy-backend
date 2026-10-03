// ESP32-CAM — Sandy's Vision
//   • Topics تحت sandy/node/<node_id>/cam/… (الأسماء بـ config.h):
//       cam/request · command · wifi · flash · stream · framesize  ← أوامر داخلة
//       cam/status  ← نبضة،  cam/event ← أحداث
//     الصورة بتنرفع بطلب لـ /api/cam/upload، مش بالوسيط.
//   • تحديث موقّع من الخادم (sandy_ota_pull.h)؛ الترقية المحلية والتلنت للتطوير بس.
// ملفات .ino (Arduino بيدمجها): capture, control (إعدادات وفلاش), http (بث محلي),
// mqtt, ota (+Telnet), upload (رفع موقّع), wifi.

#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <ArduinoOTA.h>
#include <PubSubClient.h>
#include "esp_system.h"
#include "esp_task_wdt.h"
// الأسرار قبل config.h، اللي قيمه الافتراضية بـ `#ifndef`.
#include "secrets.h"
#include "config.h"
#include "sandy_ca_roots.h"
// نفس الملفين بعقدة الغرفة.
#include "sandy_identity.h"
#include "sandy_ota_pull.h"

// ── السجل: ع الشبكة بنسخة التطوير بس (التلنت كان مفتوح بلا كلمة سر) ──
#if SANDY_DEV
WiFiServer g_telnetServer(23);
WiFiClient g_telnetClient;
#endif

class MirrorStream : public Print {
 public:
  size_t write(uint8_t c) override {
    Serial.write(c);
#if SANDY_DEV
    if (g_telnetClient && g_telnetClient.connected()) g_telnetClient.write(c);
#endif
    return 1;
  }
  size_t write(const uint8_t* buf, size_t n) override {
    Serial.write(buf, n);
#if SANDY_DEV
    if (g_telnetClient && g_telnetClient.connected()) g_telnetClient.write(buf, n);
#endif
    return n;
  }
};
MirrorStream g_log;

// ── الحارس ──
// دقيقة: ضعف أطول انتظار مقصود. الانتظارات الطويلة بتطعمه عبر `camWait`.
#define CAM_WDT_TIMEOUT_MS 60000

void camWdtFeed() { esp_task_wdt_reset(); }

// `delay` بيطعم الحارس؛ كل انتظار طويل لازم يمرق من هون.
void camWait(unsigned long ms) {
  unsigned long t0 = millis();
  while (millis() - t0 < ms) {
    unsigned long left = ms - (millis() - t0);
    delay(left > 100 ? 100 : left);
    esp_task_wdt_reset();
  }
}

// ── مخزن الإطار: مستهلك واحد بكل لحظة ──
// الالتقاط والبث البعيد وخادم البث المحلي بيتشاركوا مخزن واحد، و`esp_camera_deinit`
// تحت إيد حدا ماسك إطار بيطيّح اللوح.
static SemaphoreHandle_t g_camMutex = NULL;

bool camLock(uint32_t waitMs) {
  if (!g_camMutex) g_camMutex = xSemaphoreCreateMutex();
  if (!g_camMutex) return false;
  return xSemaphoreTake(g_camMutex, pdMS_TO_TICKS(waitMs)) == pdTRUE;
}

void camUnlock() {
  if (g_camMutex) xSemaphoreGive(g_camMutex);
}

// قفل الفلاش بعد انهيار الكهربا: علم لحاله ما بتكتب فوقه الإعدادات المحفوظة.
bool g_flashLockedByBrownout = false;

// ── Cross-file state ──
// Arduino بيلزق ملفات الـino بعد الملف الرئيسي، فاللي هون بيسبق الكل.
void mqttPublishEvent(const char* json);
bool camValidId(const String& id);
void flashSet(uint8_t level, unsigned long autoOffMs);
void flashOff();
void camRemoteStreamTick();
void camRemoteStream(bool on);
// إعلانات صريحة: Arduino بيوقف توليدها لمّا في تعريفات قبل `setup`.
void settingsLoadFromNvs();
void setupCamera();
void camReinitTick();
void connectWiFi();
void ensureWiFiConnected();
void onWiFiEvent(WiFiEvent_t event, WiFiEventInfo_t info);
void startNetworkServicesIfReady();
void updateTelnet();
void updateMQTT();
void camHttpTick();
void camWifiTick();
void flashTick();
void flashInit();
void settingsInit();
void captureAndPublishSnapshot(const String& id, unsigned int settleMs, FlashMode flash);
String camNodeId();
bool camRemoteStreaming();
void camUploadClose();
bool mqttIsConnected();
extern volatile bool g_streamViewerActive;

bool g_networkServicesStarted = false;
bool g_cameraReady = false;
bool g_snapshotPending = false;          // طلب snapshot قيد التنفيذ
String g_currentRequestId = "";          // UUID من Sandy backend
unsigned long g_lastStatusPubMs = 0;

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

// سبب آخر إقلاع، بالنبضة: انهيار كهربا = مزوّد، حارس = كود علّق، انهيار = خلل، برمجية = طلبناها.
static esp_reset_reason_t g_bootReason = ESP_RST_UNKNOWN;

// لـ `cam_mqtt.ino` (النبضة).
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

// ما في التقاط ولا سلسلة ولا بث: التنزيل بيوقف الحلقة ثواني.
bool camIdleForUpdate() {
  return !g_snapshotPending && g_burstRemaining == 0 && !g_streamViewerActive &&
         !camRemoteStreaming();
}

void setup() {
  Serial.begin(CAMERA_SERIAL_BAUD);
  delay(CAMERA_BOOT_DELAY_MS);
  Serial.println("\n[BOOT] ESP32-CAM starting  build=v4-capabilities");

  g_bootReason = esp_reset_reason();
  Serial.printf("[BOOT] سبب آخر إقلاع: %s (%d)\n",
                bootReasonText(g_bootReason), (int)g_bootReason);

  esp_task_wdt_config_t wdt = {};
  wdt.timeout_ms = CAM_WDT_TIMEOUT_MS;
  wdt.idle_core_mask = 0;
  wdt.trigger_panic = true;
  if (esp_task_wdt_reconfigure(&wdt) != ESP_OK) esp_task_wdt_init(&wdt);
  esp_task_wdt_add(NULL);

  g_camMutex = xSemaphoreCreateMutex();

  // الهويّة قبل الشبكة.
  sandyIdentityLoad(SANDY_PAIR_CODE, SANDY_MQTT_HOST, SANDY_MQTT_USER, SANDY_MQTT_PASS,
                    SANDY_WS_HMAC_KEY, SECRET_SSID, SECRET_OPTIONAL_PASS);

  settingsInit();
  flashInit();

  // بعد انهيار كهربا أول التقاط بلا فلاش: الفلاش مع المستشعر والراديو بيرجّعوا الانهيار.
  if (g_bootReason == ESP_RST_BROWNOUT) {
    g_flashLockedByBrownout = true;
    Serial.println("[BOOT] ⚠️ الفلاش متوقّف مؤقّتًا — آخر إقلاع كان انهيار كهربا. "
                   "بدّه مزوّد خمس فولت بأمبيرين ومكثّف ألف ميكرو.");
  }

  // ومضة إقلاع (بتثبت إنّ الفلاش شغّال)، إلا بعد انهيار كهربا.
  if (g_bootReason != ESP_RST_BROWNOUT) {
    flashSet(FLASH_DEFAULT_LEVEL, 250);
    delay(250);
    flashOff();
  }

  WiFi.onEvent(onWiFiEvent);
  connectWiFi();

  // لو فشلت، `camReinitTick` بيعيد المحاولة من الحلقة.
  setupCamera();

  if (g_cameraReady) settingsLoadFromNvs();

  static SandyOtaConfig ota;
  static String otaDeviceId = "cam-" + camNodeId();
  ota.board    = "cam";
  ota.host     = SANDY_UPLOAD_HOST;
  ota.deviceId = otaDeviceId.c_str();
  ota.version  = SANDY_CAM_FW_VERSION;
  ota.caRoots  = SANDY_CA_ROOTS;
  ota.idle     = camIdleForUpdate;
  ota.prepare  = []() { camRemoteStream(false); camUploadClose(); };
  ota.feed     = camWdtFeed;
  sandyOtaBegin(ota);

  // مصافحة الوسيط بدها كتلة ذاكرة متّصلة كبيرة، وبتعلّق بلا خطأ لو ما لقت.
  Serial.printf("[MEM] psram=%s free=%u largest_block=%u\n",
                psramFound() ? "yes" : "no",
                (unsigned)ESP.getFreeHeap(),
                (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
}

void loop() {
  ensureWiFiConnected();
  startNetworkServicesIfReady();

  esp_task_wdt_reset();

  if (g_networkServicesStarted) {
#if SANDY_DEV
    ArduinoOTA.handle();
    updateTelnet();
#endif
    updateMQTT();
    camHttpTick();
    camRemoteStreamTick();
  }

  // بعد الخدمات: التبديل بيقطع الشبكة بقصد.
  camWifiTick();

  flashTick();
  camReinitTick();

  if (g_snapshotPending) {
    g_snapshotPending = false;
    Serial.printf("[LOOP] dispatching capture for id=%s\n", g_currentRequestId.c_str());
    Serial.flush();
    captureAndPublishSnapshot(g_currentRequestId, g_snapshotSettleMs, g_snapshotFlash);
    Serial.println("[LOOP] capture call returned");
    Serial.flush();
  }

  // سلسلة لقطات (الدماغ بيلف الرقبة بينهن). مقارنة بالفرق عشان التفاف millis().
  if (g_burstRemaining > 0 && (long)(millis() - g_burstNextAtMs) >= 0) {
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

  sandyOtaLoop(g_networkServicesStarted && mqttIsConnected());

  delay(1);  // yield للـ TCP/WiFi stacks
}
