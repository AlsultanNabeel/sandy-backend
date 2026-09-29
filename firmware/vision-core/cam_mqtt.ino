// ESP32-CAM — MQTT

void camSyncClock();
bool camClockReady();

static WiFiClientSecure g_mqttTcp;
static PubSubClient     g_mqtt(g_mqttTcp);
static unsigned long    g_lastMqttAttemptMs = 0;

// تباعد متزايد: الوسيط بيقطع المحاولات المتلاحقة ("SSL EOF").
static unsigned long g_mqttBackoffMs = MQTT_RECONNECT_INTERVAL_MS;
#define MQTT_BACKOFF_MAX_MS 60000

const char* camStreamKey();
bool camCommandAllowed();

// ===== هوية العقدة =====
// المواضيع من كود الاقتران بنفس تحويل node_store.code_to_node_id.
static String g_topicRequest, g_topicCommand, g_topicSnapshot,
              g_topicStatus,  g_topicEvent,   g_topicWifi;

// طلب تغيير شبكة مستنّي `camLoop`: التبديل بيحجز ٢٥ ثانية ورد نداء MQTT ما لازم ينام.
static bool   g_wifiPending = false;
static String g_wifiSsid, g_wifiPass;

// مش `static`: الرفع بيوقّع بنفس المعرّف.
String camNodeId() {
  String out;
  const char* src = g_id.pair.c_str();
  for (size_t i = 0; src[i]; i++) {
    char c = src[i];
    if (c >= 'A' && c <= 'Z') c = c - 'A' + 'a';
    if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) out += c;
  }
  return out;
}

static void camBuildTopics() {
  String base = String(SANDY_TOPIC_ROOT) + camNodeId();
  g_topicRequest  = base + TOPIC_SUFFIX_REQUEST;
  g_topicCommand  = base + TOPIC_SUFFIX_COMMAND;
  g_topicSnapshot = base + TOPIC_SUFFIX_SNAPSHOT;
  g_topicStatus   = base + TOPIC_SUFFIX_STATUS;
  g_topicEvent    = base + TOPIC_SUFFIX_EVENT;
  g_topicWifi     = base + TOPIC_SUFFIX_WIFI;
  g_log.printf("[MQTT] node id = %s\n", camNodeId().c_str());
}

// ── المخرجات البسيطة ──
// قيمة نصّية لكل مخرج زي باقي الأجهزة، بتترجم لنفس أمر JSON تبع `handleCamCommand`.
static bool handleSimpleOutput(const String& out, const String& value) {
  if (out == "flash") {
    handleCamCommand(String("{\"cmd\":\"flash\",\"state\":\"") + value + "\"}");
    return true;
  }
  if (out == "flash_level") {
    // الشدّة بس، مش «اشعل»: بتتحفظ للّقطات الجاية.
    handleCamCommand(String("{\"cmd\":\"flash_level\",\"level\":") + String(value.toInt()) + "}");
    return true;
  }
  if (out == "flash_mode") {
    handleCamCommand(String("{\"cmd\":\"flash_mode\",\"mode\":\"") + value + "\"}");
    return true;
  }
  if (out == "snapshot") {
    handleCamCommand(String("{\"cmd\":\"snapshot\",\"id\":\"m") + String(millis()) + "\"}");
    return true;
  }
  if (out == "stream") {
    handleCamCommand(String("{\"cmd\":\"stream\",\"state\":\"") + value + "\"}");
    return true;
  }
  if (out == "framesize") {
    handleCamCommand(String("{\"cmd\":\"set\",\"framesize\":\"") + value + "\"}");
    return true;
  }
  // الضغط: الرقم الأصغر جودة أعلى (١٠ ممتاز، ٦٣ رديء).
  if (out == "quality") {
    // اسم ← رقم (مقياس المستشعر مقلوب).
    int q = 12;
    if      (value == "high")   q = 10;
    else if (value == "medium") q = 18;
    else if (value == "low")    q = 30;
    else                        q = value.toInt();   // رقم صريح لمين بدّه يضبط
    handleCamCommand(String("{\"cmd\":\"set\",\"quality\":") + String(q) + "}");
    return true;
  }
  return false;
}

static void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String value;
  value.reserve(length);
  for (unsigned int i = 0; i < length; i++) value += (char)payload[i];

  String t(topic);

  // رسالة الشبكة ما بتنكتب بالسجل (فيها كلمة السر)؛ الباقي أول ستين حرف.
  if (t == g_topicWifi) {
    g_log.printf("[MQTT] %s (%u بايت، المحتوى مخفي)\n", topic, length);
  } else {
    g_log.printf("[MQTT] %s = %.60s%s\n", topic, value.c_str(), length > 60 ? "…" : "");
  }

  // قناة الأوامر: فلاش، إعدادات، بث، سلسلة لقطات
  if (t == g_topicWifi) {
    // "<اسم>\n<كلمة السر>" (السطر الجديد ما بيكون جوّاهن).
    int nl = value.indexOf('\n');
    if (nl < 0) { g_log.println("[WIFI] no password line"); return; }
    String ssid = value.substring(0, nl);
    String pass = value.substring(nl + 1);
    // حدود المعيار: الاسم ≤ ٣٢، كلمة السر فاضية أو ٨..٦٤. غير هيك رفض، مش قصّ.
    if (ssid.length() == 0 || ssid.length() > 32 || pass.length() > 64 ||
        (pass.length() > 0 && pass.length() < 8)) {
      g_log.println("[WIFI] ignored — ssid/password outside the Wi-Fi limits");
      return;
    }
    g_wifiSsid = ssid;
    g_wifiPass = pass;
    g_wifiPending = true;
    g_log.printf("[WIFI] switch queued -> '%s'\n", g_wifiSsid.c_str());
    return;
  }

  if (t == g_topicCommand) {
    handleCamCommand(value);
    return;
  }

  if (t == g_topicRequest) {
    // الصيغة القديمة، بنفس مسار الأوامر.
    handleCamCommand(String("{\"cmd\":\"snapshot\",\"id\":\"") +
                     jsonStr(value, "id", String("r") + String(millis())) + "\"}");
  } else {
    // آخر مقطع من الموضوع = اسم المخرج.
    int slash = t.lastIndexOf('/');
    String out = slash >= 0 ? t.substring(slash + 1) : String();
    // مواضيعنا الراجعة علينا مش أوامر.
    if (out == "status" || out == "snapshot" || out == "event" ||
        out == "request" || out == "command") return;
    if (handleSimpleOutput(out, value)) return;
    g_log.printf("[CB] unhandled topic '%s'\n", t.c_str());
  }
}

void setupMQTT() {
  // قبل أي اشتراك أو نشر، وإلا بتروح ع "sandy/node//cam/...".
  camBuildTopics();
  // تحقّق من شهادة الوسيط.
  g_mqttTcp.setCACert(SANDY_CA_ROOTS);
  // الافتراضي دقيقتين، أطول من الحارس.
  g_mqttTcp.setHandshakeTimeout(15);
  g_mqttTcp.setTimeout(15000);
  g_mqtt.setServer(g_id.mqttHost.c_str(), SANDY_MQTT_PORT);
  g_mqtt.setCallback(mqttCallback);
  g_mqtt.setBufferSize(MQTT_BUFFER_SIZE);  // كبير لاستيعاب chunks
  g_mqtt.setSocketTimeout(15);             // مهلة كافية لـ TLS handshake
  g_mqtt.setKeepAlive(30);                 // keepalive معقول
  g_log.printf("[MQTT] configured for %s:%d\n", g_id.mqttHost.c_str(), SANDY_MQTT_PORT);
}

static bool mqttReconnect() {
  if (g_mqtt.connected()) return true;
  unsigned long now = millis();
  if (now - g_lastMqttAttemptMs < g_mqttBackoffMs) return false;
  g_lastMqttAttemptMs = now;

  // الشهادة بتحتاج ساعة صحيحة.
  camSyncClock();
  if (!camClockReady()) return false;

  // المعرّف من الـMAC كامل (أوطى أربع بايتات فيهم بادئة المصنّع).
  char macHex[13];
  snprintf(macHex, sizeof(macHex), "%012llx", (unsigned long long)ESP.getEfuseMac());
  String clientId = "sandy-cam-" + camNodeId() + "-" + String(macHex);

  // فرّق فشل الاسم عن فشل المصافحة؛ hostByName ممكن ترجّع «نجاح» بعنوان صفري.
  IPAddress brokerIp;
  bool resolved = WiFi.hostByName(g_id.mqttHost.c_str(), brokerIp) &&
                  brokerIp != IPAddress((uint32_t)0);
  if (!resolved) {
    g_log.printf("[MQTT] DNS not ready (%s) — will retry\n",
                 brokerIp.toString().c_str());
    return false;
  }
  g_log.printf("[MQTT] dns ok → %s\n", brokerIp.toString().c_str());

  g_log.printf("[MQTT] connecting as %s (free=%u largest=%u) ...\n",
               clientId.c_str(), (unsigned)ESP.getFreeHeap(),
               (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
  // وصيّة «طفيت» عند الوسيط لو انقطعنا.
  static const char* kWillMsg = "{\"online\":false}";
  if (g_mqtt.connect(clientId.c_str(), g_id.mqttUser.c_str(), g_id.mqttPass.c_str(),
                     g_topicStatus.c_str(), 1, true, kWillMsg)) {
    g_log.println("[MQTT] connected");
    // امسح الوصيّة المحفوظة بـ«شغّالة» محفوظة.
    g_mqtt.publish(g_topicStatus.c_str(), "{\"online\":true}", true);
    bool subOk = g_mqtt.subscribe(g_topicRequest.c_str(), 0);  // QoS 0 — لا PUBACK يعلّق الـ TLS write
    subOk = g_mqtt.subscribe(g_topicCommand.c_str(), 0) && subOk;
    subOk = g_mqtt.subscribe(g_topicWifi.c_str(), 0) && subOk;
    // اشتراك بالاسم مش `cam/+`: النجمة كانت ترجّع كل منشوراتنا وتأخّر الطلبات لحدّ ما الخادم يستسلم.
    // لازم نسمع ع `snapshot` و`quality` لأنّ النبضة بتعلنهم.
    static const char* kSimpleOutputs[] = {
      "flash", "flash_level", "flash_mode", "stream", "framesize", "snapshot", "quality"
    };
    String base = String(SANDY_TOPIC_ROOT) + camNodeId() + "/cam/";
    for (const char* out : kSimpleOutputs) {
      subOk = g_mqtt.subscribe((base + out).c_str(), 0) && subOk;
    }
    if (!subOk) {
      // متّصلة وما بتسمع أسوأ من مقطوعة: منعيد.
      g_log.println("[MQTT] subscribe refused — reconnecting");
      g_mqtt.disconnect();
      return false;
    }
    g_mqttBackoffMs = MQTT_RECONNECT_INTERVAL_MS;   // نجحنا → رجّع الانتظار لأصله
    publishFullStatus();                     // أول ما نتصل: عرّف عن حالك كاملة
    return true;
  }
  char tlsErr[128] = {0};
  g_mqttTcp.lastError(tlsErr, sizeof(tlsErr));
  g_mqttTcp.stop();   // نظّف المقبس قبل المحاولة الجاية
  g_mqttBackoffMs = min(g_mqttBackoffMs * 2, (unsigned long)MQTT_BACKOFF_MAX_MS);
  g_log.printf("[MQTT] connect failed rc=%d tls='%s' — next try in %lus\n",
               g_mqtt.state(), tlsErr[0] ? tlsErr : "none", g_mqttBackoffMs / 1000);
  return false;
}

// تغيير الشبكة من الحلقة الرئيسية (بيحجز ٢٥ ثانية).
void camWifiTick() {
  if (!g_wifiPending) return;
  g_wifiPending = false;
  bool ok = camSwitchNetwork(g_wifiSsid, g_wifiPass);
  // النتيجة بتبيّن بالنبضة الجاية (اسم الشبكة).
  g_log.printf("[WIFI] switch %s\n", ok ? "ok" : "rolled back");
}

esp_reset_reason_t camBootReason();

static void publishCamStatus() {
  if (!g_mqtt.connected()) return;
  unsigned long now = millis();
  if (now - g_lastStatusPubMs < STATUS_POST_INTERVAL_MS) return;
  g_lastStatusPubMs = now;

  // النبضة: ip و board (نفس حقول الدماغ)، `boot` = سبب آخر إقلاع، `stream_key` للخادم بس.
  // اسم الشبكة بيتهرّب (علامة تنصيص كانت تكسر JSON).
  String ssidEsc;
  for (const char* c = camSsid(); *c; c++) {
    if (*c == '"' || *c == '\\') ssidEsc += '\\';
    if ((unsigned char)*c >= 0x20) ssidEsc += *c;
  }
  char buf[760];
  int n = snprintf(buf, sizeof(buf),
           "{\"uptime_s\":%lu,\"rssi\":%d,\"heap\":%u,\"psram\":%u,"
           "\"camera_ready\":%s,\"flash_on\":%s,\"stream\":%s,\"boot\":%d,"
           "\"fw\":\"%s\",\"stream_key\":\"%s\",\"online\":true,"
           "\"ip\":\"%s\",\"ssid\":\"%s\",\"board\":\"%s\","
           "\"outputs\":[{\"id\":\"flash\",\"kind\":\"relay\"},"
           "{\"id\":\"flash_level\",\"kind\":\"pwm\"},"
           "{\"id\":\"flash_mode\",\"kind\":\"pwm\"},"
           "{\"id\":\"snapshot\",\"kind\":\"pwm\"},"
           "{\"id\":\"stream\",\"kind\":\"relay\"},"
           "{\"id\":\"framesize\",\"kind\":\"pwm\"},"
           "{\"id\":\"quality\",\"kind\":\"pwm\"}]}",
           now / 1000,
           WiFi.RSSI(),
           (unsigned)ESP.getFreeHeap(),
           (unsigned)ESP.getFreePsram(),
           g_cameraReady ? "true" : "false",
           flashIsOn() ? "true" : "false",
           camHttpRunning() ? "true" : "false",
           (int)camBootReason(),
           SANDY_CAM_FW_VERSION, camStreamKey(),
           WiFi.localIP().toString().c_str(), ssidEsc.c_str(),
           SANDY_CAM_BOARD_ID);
  if (n <= 0 || n >= (int)sizeof(buf)) {
    g_log.println("[HB] heartbeat did not fit — skipped");
    return;
  }
  g_mqtt.publish(g_topicStatus.c_str(), buf, false);

  // heartbeat ع التيلنت: الـ loop شغّال
  g_log.printf("[HB] up=%lus rssi=%d heap=%u cam=%s mqtt=ok\n",
               now / 1000, WiFi.RSSI(), (unsigned)ESP.getFreeHeap(),
               g_cameraReady ? "yes" : "NO");
}

void updateMQTT() {
  static unsigned long lastNoWifiLogMs = 0;
  if (WiFi.status() != WL_CONNECTED) {
    unsigned long now = millis();
    if (now - lastNoWifiLogMs > 5000) {
      lastNoWifiLogMs = now;
      g_log.println("[HB] waiting for WiFi...");
    }
    return;
  }
  if (!g_mqtt.connected()) { mqttReconnect(); return; }
  g_mqtt.loop();
  publishCamStatus();
}

void mqttPublishEvent(const char* json) {
  if (!g_mqtt.connected()) return;
  g_mqtt.publish(g_topicEvent.c_str(), json, false);
}

bool mqttIsConnected() { return g_mqtt.connected(); }

bool mqttPublishStatusJson(const char* json) {
  if (!g_mqtt.connected()) return false;
  return g_mqtt.publish(g_topicStatus.c_str(), json, false);
}
