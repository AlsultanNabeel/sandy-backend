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
              g_topicStatus,  g_topicEvent,   g_topicWifi;

// طلب تغيير شبكة، مستنّي الحلقة الرئيسية.
//
// **ما بينفّذ برد نداء MQTT**: التبديل بيحجز لخمسة وعشرين ثانية، ورد النداء ما
// بيجوز ينام — لو نام بتتكدّس الرسائل وبيسقط الاتصال، فبتخسر اللوح وإنت
// بتحاول تنقله. فبنسجّل الطلب هون وبتنفّذه `camLoop`.
static bool   g_wifiPending = false;
static String g_wifiSsid, g_wifiPass;

// مش `static` — الرفع بيستعملها كمان، ولازم يوقّع بنفس المعرّف اللي الخادم
// بيعرف الوحدة فيه. نسخة تانية من نفس التحويل كانت رح تفترق يومًا ما.
String camNodeId() {
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
  g_topicWifi     = base + TOPIC_SUFFIX_WIFI;
  g_log.printf("[MQTT] node id = %s\n", camNodeId().c_str());
}

// ── المخرجات البسيطة ─────────────────────────────────────────────────────────
//
// التطبيق بيتعامل مع كل الأجهزة بنفس الشكل: قيمة نصّية بسيطة ع موضوع لكل مخرج.
// الكاميرا كانت الوحيدة اللي بدها JSON، فما كانت بتظهر بصفحة التحكّم زي غيرها.
//
// هاد بيترجم القيمة البسيطة لنفس أمر الـ JSON اللي `handleCamCommand` بيفهمه —
// مسار تنفيذ واحد، مش تنين لازم يضلّوا متطابقين.
static bool handleSimpleOutput(const String& out, const String& value) {
  if (out == "flash") {
    handleCamCommand(String("{\"cmd\":\"flash\",\"state\":\"") + value + "\"}");
    return true;
  }
  if (out == "flash_level") {
    handleCamCommand(String("{\"cmd\":\"flash\",\"state\":\"on\",\"level\":") + value + "}");
    return true;
  }
  if (out == "flash_mode") {
    handleCamCommand(String("{\"cmd\":\"flash_mode\",\"mode\":\"") + value + "\"}");
    return true;
  }
  if (out == "snapshot") {
    handleCamCommand(String("{\"cmd\":\"snapshot\",\"id\":\"") + String(millis()) + "\"}");
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
  // الضغط — **الرقم الأصغر جودة أعلى** (عشرة ممتاز، ثلاثة وستّين رديء).
  //
  // الصورة بتنضغط جوّا المستشعر لحظة الالتقاط، فهاد الرقم هو **الوحيد** اللي
  // بيقرّر التفاصيل اللي بتوصل. كان مثبّتًا ع اثنتي عشرة بالكود وما إله زرّ:
  // المالك بيقدر يكبّر الدقّة وما بيقدر يحسّن الوضوح، وهما إشيان مختلفان —
  // صورة كبيرة بضغط عالي بتضلّ مغبّشة.
  if (out == "quality") {
    // اسم ← رقم. والمقياس مقلوب عند المستشعر: الأصغر أوضح.
    //
    // ما بنمرّر الرقم للمستخدم لأنه بيقرا بالعكس. وما بنمرّر الاسم للمستشعر
    // لأنه ما بيفهمه. الترجمة هون، بسطر واحد، ومكتوب جنبه ليش.
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
  // مقصوص عند مئة وعشرين حرفًا. سطر السجل نفسه كان جزءًا من البطء: حمولة
  // القطعة حوالي ألف وأربعمية حرف، وطباعتها كاملة عبر التسلسلي/التلنت بتوقف
  // الحلقة الرئيسية. وما بتضيف معلومة — أول مئة حرف بتقول أي رسالة هي.
  if (length > 120) {
    g_log.printf("[MQTT] %s = %.120s… (%u بايت)\n", topic, value.c_str(), length);
  } else {
    g_log.printf("[MQTT] %s = %s\n", topic, value.c_str());
  }

  String t(topic);

  // قناة الأوامر: كل قدرات الكاميرا (فلاش، إعدادات، بث، سلسلة لقطات)
  if (t == g_topicWifi) {
    // الحمولة: "<اسم>\n<كلمة السر>". سطر جديد فاصلًا لأنه الحرف الوحيد اللي
    // ما بيقدر يكون جوّا اسم شبكة ولا كلمة سر.
    int nl = value.indexOf('\n');
    if (nl < 0) { g_log.println("[WIFI] no password line"); return; }
    g_wifiSsid = value.substring(0, nl);
    g_wifiPass = value.substring(nl + 1);
    g_wifiPending = true;
    g_log.printf("[WIFI] switch queued -> '%s'\n", g_wifiSsid.c_str());
    return;
  }

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
    // آخر مقطع من الموضوع هو اسم المخرج. النبضة تبعتنا بترجع علينا بنفس
    // الشجرة، فلازم تُتجاهل صراحة وإلا فُسّرت كأمر.
    int slash = t.lastIndexOf('/');
    String out = slash >= 0 ? t.substring(slash + 1) : String();
    // مواضيعنا نحنا راجعة علينا — لازم تُتجاهل صراحة وإلا انفسّرت كأوامر.
    if (out == "status" || out == "snapshot" || out == "event" ||
        out == "request" || out == "command") return;
    if (handleSimpleOutput(out, value)) return;
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
    g_mqtt.subscribe(g_topicWifi.c_str(), 0);
    // مخارج الكاميرا البسيطة — **بالاسم، مش `cam/+`**.
    //
    // الشجرة وحدة: اللوح بينشر تحت `cam/` وبيسمع تحت `cam/`. فاشتراك بنجمة
    // بيرجّعله كل إشي بينشره. وهاد ما كان خطأ منطقيًّا — في سطر تحت بيتجاهل
    // مواضيعنا صراحة — بس كان **خطأ كلفة**، وهي اللي كسرت الالتقاط:
    //
    // كل صورة تمان قطع. الوسيط بيرجّعهن كلهن للّوح: حوالي أحد عشر كيلوبايت
    // بتنفكّ من التشفير، بتنسخ لسلسلة، وبتنطبع كاملة ع السجل — قبل ما
    // `g_mqtt.loop()` يفضى للطلب اللي بعده. أول صورة بعد الإقلاع رجعت بثانية
    // وتلث؛ اللي بعدها لقيت اللوح مشغول بصدى اللي قبلها، فصار الردّ أربعتعش
    // ثانية، والخادم بيستنّى خمستعش. وكل إعادة محاولة بتضيف تمن قطع صدى تانية،
    // فالتأخير بيكبر مع كل ضغطة.
    //
    // ولاحظ: `snapshot` مش هون. اللوح بينشر القطع عليه، فالاشتراك عليه صدى
    // محض — وكان متجاهلًا أصلًا، يعني ما اشتغل ولا مرّة كزرّ.
    static const char* kSimpleOutputs[] = {
      "flash", "flash_level", "flash_mode", "stream", "framesize"
    };
    String base = String(SANDY_TOPIC_ROOT) + camNodeId() + "/cam/";
    for (const char* out : kSimpleOutputs) {
      g_mqtt.subscribe((base + out).c_str(), 0);
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

// بينفّذ طلب تغيير الشبكة، من الحلقة الرئيسية.
//
// هون مش برد النداء: التبديل بيحجز خمسة وعشرين ثانية، ورد نداء MQTT اللي بينام
// بيوقّف قراءة المقبس وبيسقّط الاتصال — يعني بتخسر اللوح وإنت بتحاول تنقله.
void camWifiTick() {
  if (!g_wifiPending) return;
  g_wifiPending = false;
  bool ok = camSwitchNetwork(g_wifiSsid, g_wifiPass);
  // ما في رسالة «نجح». النبضة الجاية بتقول اسم الشبكة اللي الكاميرا عليها
  // فعلًا — واللي رجعت بتقول القديم. مصدر واحد للحقيقة بدل قناتين بيفترقوا.
  g_log.printf("[WIFI] switch %s\n", ok ? "ok" : "rolled back");
}

esp_reset_reason_t camBootReason();

static void publishCamStatus() {
  if (!g_mqtt.connected()) return;
  unsigned long now = millis();
  if (now - g_lastStatusPubMs < STATUS_POST_INTERVAL_MS) return;
  g_lastStatusPubMs = now;

  // العنوان والاسم بالنبضة.
  //
  // بلاهم، «شو عنوان الكاميرا؟» ما إله جواب بكل النظام: الراوتر بيوزّع عنوان
  // بيتغيّر، والكاميرا ما بتقوله لحدا. سؤال بسيط بينتهي بمسح ٢٥٤ عنوان
  // وتخمين أي لوح ردّ — وهاد صار.
  //
  // نفس الحقلين اللي عند الدماغ بالضبط (ip, board)، فالخادم بيقراهم بنفس
  // المسار بلا ولا سطر جديد عنده.
  // `boot` = سبب آخر إقلاع.
  //
  // بدونه، «بتعمل ريستارت» بتحتاج كبل وحظّ: لازم تكون شابك ومتفرّج بالثانية
  // اللي صار فيها. وهي بتنشره كل عشر ثواني، فالسبب بيوصلك وإنت بعيد — والأهمّ
  // إنه بيوصل **بعد** ما يصير، مش وقتها.
  char buf[600];
  snprintf(buf, sizeof(buf),
           "{\"uptime_s\":%lu,\"rssi\":%d,\"heap\":%u,\"psram\":%u,"
           "\"camera_ready\":%s,\"flash_on\":%s,\"stream\":%s,\"boot\":%d,"
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
           ESP.getFreeHeap(),
           ESP.getFreePsram(),
           g_cameraReady ? "true" : "false",
           flashIsOn() ? "true" : "false",
           camHttpRunning() ? "true" : "false",
           (int)camBootReason(),
           WiFi.localIP().toString().c_str(), camSsid(),
           SANDY_CAM_BOARD_ID);
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

// دورة واحدة للمكتبة — بتنادى بين قطع الصورة.
//
// حلقة النشر بتشتغل خارج `loop()` الرئيسية، يعني `g_mqtt.loop()` ما بينادى
// طول الإرسال. والمكتبة بتحتاجه: بيفضّي المقبس، وبيردّ ع نبضة الوسيط. بدونه
// الإرسال بيصير كتابة عمياء لثانية كاملة — والوسيط بيشوف لوحًا سكت فجأة.
void mqttServiceOnce() {
  if (g_mqtt.connected()) g_mqtt.loop();
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
