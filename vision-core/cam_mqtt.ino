// =========================
// ESP32-CAM — MQTT (HiveMQ)
// =========================

static WiFiClientSecure g_mqttTcp;
static PubSubClient     g_mqtt(g_mqttTcp);
static unsigned long    g_lastMqttAttemptMs = 0;

// إعادة المحاولة بتباعد متزايد. الوسيط بيعتبر المحاولات المتلاحقة إغراقاً
// وبيقطع الاتصال فوراً ("SSL EOF")، فكل فشل بيضاعف الانتظار لحد سقف.
static unsigned long g_mqttBackoffMs = MQTT_RECONNECT_INTERVAL_MS;
#define MQTT_BACKOFF_MAX_MS 60000

// Rate limit / safety: حد أدنى للفترة بين طلبات snapshot — حماية من الحرارة + spam
#define SNAPSHOT_MIN_GAP_MS  1500
static unsigned long g_lastSnapshotAtMs = 0;

// ===== هوية العقدة =====
// المواضيع بتنبنى مرة وحدة عند الإقلاع من كود الاقتران، بنفس التحويل تبع
// الخادم (node_store.code_to_node_id): حروف صغيرة، وأرقام وحروف بس.
static String g_topicRequest, g_topicCommand, g_topicSnapshot,
              g_topicStatus,  g_topicEvent;

static String camNodeId() {
  String out;
  const char* src = SANDY_PAIR_CODE;
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
  g_log.printf("[MQTT] node id = %s\n", camNodeId().c_str());
}

static void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String value;
  value.reserve(length);
  for (unsigned int i = 0; i < length; i++) value += (char)payload[i];
  g_log.printf("[MQTT] %s = %s\n", topic, value.c_str());

  String t(topic);

  // قناة الأوامر: كل قدرات الكاميرا (فلاش، إعدادات، بث، سلسلة لقطات)
  if (t == g_topicCommand) {
    handleCamCommand(value);
    return;
  }

  if (t == g_topicRequest) {
    g_log.println("[CB] matched cam/request");
    unsigned long now = millis();
    if (g_snapshotPending) {
      g_log.println("[CAM] snapshot already pending — ignoring duplicate request");
      return;
    }
    if (g_lastSnapshotAtMs && now - g_lastSnapshotAtMs < SNAPSHOT_MIN_GAP_MS) {
      g_log.printf("[CAM] rate-limited — last snap was %lums ago\n", now - g_lastSnapshotAtMs);
      return;
    }
    g_lastSnapshotAtMs = now;

    String id;
    int idx = value.indexOf("\"id\":\"");
    if (idx < 0) idx = value.indexOf("\"id\": \"");
    if (idx >= 0) {
      int start = value.indexOf("\"", idx + 4) + 1;
      int end = value.indexOf("\"", start);
      if (end > start) id = value.substring(start, end);
    }
    if (id.length() == 0) id = String(millis());
    g_currentRequestId = id;
    // الطلب البسيط بيمشي على الوضع المحفوظ للفلاش وبلا انتظار
    g_snapshotSettleMs = 0;
    g_snapshotFlash = g_flashMode;
    g_snapshotPending = true;
    g_log.printf("[CAM] snapshot requested id=%s\n", id.c_str());
  } else {
    g_log.printf("[CB] unhandled topic '%s'\n", t.c_str());
  }
}

void setupMQTT() {
  // قبل أي اشتراك أو نشر: بلا مواضيع، كل رسالة بتروح ع "sandy/node//cam/..."
  // وما في حدا سامع، والكاميرا بتبيّن شغّالة وهي فعليًا معزولة.
  camBuildTopics();
  g_mqttTcp.setInsecure();
  g_mqtt.setServer(SANDY_MQTT_HOST, SANDY_MQTT_PORT);
  g_mqtt.setCallback(mqttCallback);
  g_mqtt.setBufferSize(MQTT_BUFFER_SIZE);  // كبير لاستيعاب chunks
  g_mqtt.setSocketTimeout(15);             // مهلة كافية لـ TLS handshake
  g_mqtt.setKeepAlive(30);                 // keepalive معقول
  g_log.printf("[MQTT] configured for %s:%d\n", SANDY_MQTT_HOST, SANDY_MQTT_PORT);
}

static bool mqttReconnect() {
  if (g_mqtt.connected()) return true;
  unsigned long now = millis();
  if (now - g_lastMqttAttemptMs < g_mqttBackoffMs) return false;
  g_lastMqttAttemptMs = now;

  String clientId = "sandy-cam-";
  clientId += String((uint32_t)ESP.getEfuseMac(), HEX);

  // نفرّق بين فشل ترجمة الاسم وفشل المصافحة المشفّرة — الاثنين بيرجّعوا نفس الرقم
  // ملاحظة: hostByName بترجع "نجاح" مع عنوان صفري لو خدمة الأسماء لسا مش جاهزة
  // بعد وصل الشبكة. العنوان الصفري فشل، مش نجاح.
  IPAddress brokerIp;
  bool resolved = WiFi.hostByName(SANDY_MQTT_HOST, brokerIp) &&
                  brokerIp != IPAddress((uint32_t)0);
  if (!resolved) {
    g_log.printf("[MQTT] DNS not ready (%s) — will retry\n",
                 brokerIp.toString().c_str());
    return false;
  }
  g_log.printf("[MQTT] dns ok → %s\n", brokerIp.toString().c_str());

  g_log.printf("[MQTT] connecting as %s (free=%u largest=%u) ...\n",
               clientId.c_str(), ESP.getFreeHeap(),
               heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
  if (g_mqtt.connect(clientId.c_str(), SANDY_MQTT_USER, SANDY_MQTT_PASS)) {
    g_log.println("[MQTT] connected");
    g_mqtt.subscribe(g_topicRequest.c_str(), 0);  // QoS 0 — لا PUBACK يعلّق الـ TLS write
    g_mqtt.subscribe(g_topicCommand.c_str(), 0);
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

static void publishCamStatus() {
  if (!g_mqtt.connected()) return;
  unsigned long now = millis();
  if (now - g_lastStatusPubMs < STATUS_POST_INTERVAL_MS) return;
  g_lastStatusPubMs = now;

  char buf[260];
  snprintf(buf, sizeof(buf),
           "{\"uptime_s\":%lu,\"rssi\":%d,\"heap\":%u,\"psram\":%u,"
           "\"camera_ready\":%s,\"flash_on\":%s,\"stream\":%s}",
           now / 1000,
           WiFi.RSSI(),
           ESP.getFreeHeap(),
           ESP.getFreePsram(),
           g_cameraReady ? "true" : "false",
           flashIsOn() ? "true" : "false",
           camHttpRunning() ? "true" : "false");
  g_mqtt.publish(g_topicStatus.c_str(), buf, false);

  // heartbeat واضح ع التيلنت — يأكد إنو الـ loop شغّال
  g_log.printf("[HB] up=%lus rssi=%d heap=%u cam=%s mqtt=ok\n",
               now / 1000, WiFi.RSSI(), ESP.getFreeHeap(),
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

// تُستخدم من cam_capture.ino لنشر chunk
bool mqttPublishChunk(const char* payload, unsigned int len) {
  if (!g_mqtt.connected()) return false;
  return g_mqtt.publish(g_topicSnapshot.c_str(), (const uint8_t*)payload, len, false);
}

void mqttPublishEvent(const char* json) {
  if (!g_mqtt.connected()) return;
  g_mqtt.publish(g_topicEvent.c_str(), json, false);
}

// حالة كاملة (كل الإعدادات) — أطول من الحالة الدورية، فبتنشر عند الطلب فقط
bool mqttPublishStatusJson(const char* json) {
  if (!g_mqtt.connected()) return false;
  return g_mqtt.publish(g_topicStatus.c_str(), json, false);
}
