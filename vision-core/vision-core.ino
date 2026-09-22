// =========================
// ESP32-CAM — Sandy's Vision (MQTT-based)
// =========================
//   • WiFi مباشر
//   • MQTT (HiveMQ) — نفس البروكر تبع Sandy
//   • Topics — تحت شجرة الروبوت (sandy/node/<node_id>/cam/…، الأسماء بـ config.h):
//       cam/request · command · wifi · flash · stream · framesize  ← أوامر داخلة
//       cam/status  ← حالة الكاميرا (نبضة)،  cam/event ← أحداث
//     الصورة نفسها ما بتمرّ بالوسيط: بتنرفع بطلب واحد لـ /api/cam/upload.
//   • OTA + Telnet
//
// التقسيم على ملفات .ino — يدمجها Arduino IDE تلقائياً:
//   vision-core.ino  — globals + setup + loop (هذا الملف)
//   cam_capture.ino  — esp_camera init + JPEG capture
//   cam_control.ino  — إعدادات الكاميرا والفلاش (محفوظة)
//   cam_http.ino     — البث المباشر على الشبكة المحلية
//   cam_mqtt.ino     — MQTT connect / subscribe / status
//   cam_ota.ino      — OTA + Telnet
//   cam_upload.ino   — رفع الصورة للخادم (موقّع، مع مفتاح الكاميرا الخاص)
//   cam_wifi.ino     — WiFi + diagnostics

#include <Arduino.h>
#include "esp_camera.h"
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <ArduinoOTA.h>
#include <PubSubClient.h>
#include "esp_system.h"
#include "esp_task_wdt.h"
// **الأسرار قبل الإعدادات.** `config.h` بيعطي قيمًا افتراضية بـ `#ifndef` —
// والترتيب العكسي كان بيخلّي أي قيمة بالأسرار (زي مفتاح البث المحلي) تيجي
// متأخرة وتنتهي تحذير «إعادة تعريف» بدل ما تسري.
#include "secrets.h"
#include "config.h"
#include "sandy_ca_roots.h"

// ── السجل ──────────────────────────────────────────────────────────────────
//
// **نسخة التطوير بس بتمرّر السجل ع الشبكة.** مرآة التلنت كانت شغّالة بكل
// نسخة، بلا كلمة سر، ع منفذ ثلاثة وعشرين — وأي جهاز بالبيت كان بيقرا كل سطر:
// عناوين، وأوامر، ولحظة تغيير الواي فاي كلمة سرّها كمان. بالنسخة اللي بتنباع
// السجل ع الكبل وبس.
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

// ── الحارس ─────────────────────────────────────────────────────────────────
//
// **ما كان في حارس، وفي عشرة أماكن ممكن تعلّق.** مزامنة الساعة، مصافحة الوسيط،
// الرفع، تبديل الشبكة، إعادة تشغيل المستشعر، وإيقاف خادم البث وفي حدا بيتفرّج.
// أي وحدة منهن علقت كانت بتعني لوحًا ميّت لحدّ ما حدا يشيل الفيشة — والفلاش
// ضايل مشتعل إذا صادف إنه كان شغّال لحظتها، لأنّ مؤقّت الأمان تبعه بيمشي من
// نفس الحلقة اللي علقت.
//
// دقيقة كاملة: أطول انتظار مقصود باللوح (رفع + قراءة الردّ) نصّها. وكل انتظار
// طويل بيطعم الحارس بنفسه عبر `camWait`، فالحارس ما بيعضّ إلا تعليقًا حقيقيًّا.
#define CAM_WDT_TIMEOUT_MS 60000

void camWdtFeed() { esp_task_wdt_reset(); }

// `delay` اللي بيطعم الحارس — كل انتظار طويل باللوح لازم يمرق من هون.
void camWait(unsigned long ms) {
  unsigned long t0 = millis();
  while (millis() - t0 < ms) {
    unsigned long left = ms - (millis() - t0);
    delay(left > 100 ? 100 : left);
    esp_task_wdt_reset();
  }
}

// ── مخزن الإطار: مستهلك واحد بكل لحظة ────────────────────────────────────
//
// المستشعر عنده مخزن إطار **واحد**، وتلات أطراف بتطلبه: الالتقاط بالحلقة،
// والبث البعيد بالحلقة، وخادم البث المحلي بمهمّته الخاصة. والأخطر: إنعاش
// المستشعر بيعمل `esp_camera_deinit` — لو صار وخادم البث ماسك إطارًا، الذاكرة
// بتنسحب من تحت إيده والبورد بيطيح. القفل هون بيخلّي كل واحد ياخد دوره.
static SemaphoreHandle_t g_camMutex = NULL;

bool camLock(uint32_t waitMs) {
  if (!g_camMutex) g_camMutex = xSemaphoreCreateMutex();
  if (!g_camMutex) return false;
  return xSemaphoreTake(g_camMutex, pdMS_TO_TICKS(waitMs)) == pdTRUE;
}

void camUnlock() {
  if (g_camMutex) xSemaphoreGive(g_camMutex);
}

// **قفل الفلاش بعد انهيار الكهربا — قرار ما بيتغيّر بالإعدادات.**
//
// كان بيتطبّق بتصفير وضع الفلاش، وبعد سطرين بترجع الإعدادات المحفوظة وبتكتب
// فوقه — يعني الحماية كانت بتنلغى قبل أول صورة. علم لحاله ما حدا بيلمسه.
bool g_flashLockedByBrownout = false;

// ── Cross-file state ────────────────────────────────────────────
// كل متغيّر بيستعمله أكتر من ملف لازم يكون هون: Arduino بيلزق ملفات الـino
// ورا بعض أبجدياً بعد الملف الرئيسي، فاللي هون بيسبق الكل.
void mqttPublishEvent(const char* json);
bool camValidId(const String& id);
void flashSet(uint8_t level, unsigned long autoOffMs);
void flashOff();
void camRemoteStreamTick();
void camRemoteStream(bool on);
// أردوينو بيولّد إعلانات الدوال لحاله، بس بيوقف عن هيك لمّا يكون في تعريفات
// قبل `setup` — وهاد اللي صار لمّا ضفنا قراءة سبب الإقلاع. الإعلان الصريح
// بيشيل الاعتماد ع سلوك ضمني بيتغيّر مع أي إضافة فوق.
void settingsLoadFromNvs();
void setupCamera();
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

  // الحارس قبل أي إشي ممكن يعلّق.
  esp_task_wdt_config_t wdt = {};
  wdt.timeout_ms = CAM_WDT_TIMEOUT_MS;
  wdt.idle_core_mask = 0;
  wdt.trigger_panic = true;
  if (esp_task_wdt_reconfigure(&wdt) != ESP_OK) esp_task_wdt_init(&wdt);
  esp_task_wdt_add(NULL);

  g_camMutex = xSemaphoreCreateMutex();

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
    g_flashLockedByBrownout = true;
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
  // مقارنة بالفرق، مش بالقيمة: العدّاد بيلفّ بعد تسعة وأربعين يوم تشغيل،
  // والمقارنة المباشرة وقتها بتطلق اللقطات كلها مرّة وحدة أو بتوقفها.
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

  delay(1);  // yield للـ TCP/WiFi stacks
}
