// =========================
// ESP32-CAM — OTA + Telnet
// =========================

void setupOTA() {
  ArduinoOTA.setHostname(SANDY_OTA_HOSTNAME);
  ArduinoOTA.setPassword(SANDY_OTA_PASSWORD);
  ArduinoOTA.onStart([]() {
    g_log.println("[OTA] update starting");
  });
  ArduinoOTA.onEnd([]() {
    g_log.println("[OTA] complete — rebooting");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    static unsigned int lastTen = 999;
    unsigned int ten = (progress * 10) / total;
    if (ten != lastTen) { lastTen = ten; g_log.printf("[OTA] %u%%\n", ten * 10); }
  });
  ArduinoOTA.onError([](ota_error_t error) {
    g_log.printf("[OTA] error %u\n", (unsigned)error);
  });
  ArduinoOTA.begin();
  g_log.printf("[OTA] ready as '%s' @ %s\n",
               SANDY_OTA_HOSTNAME, WiFi.localIP().toString().c_str());
}

void setupTelnet() {
  g_telnetServer.begin();
  g_telnetServer.setNoDelay(true);
  g_log.printf("[TELNET] port 23 — connect via nc %s 23\n",
               WiFi.localIP().toString().c_str());
}

void updateTelnet() {
  if (g_telnetServer.hasClient()) {
    if (g_telnetClient && g_telnetClient.connected()) {
      WiFiClient n = g_telnetServer.available();
      n.println("[TELNET] busy"); n.stop();
    } else {
      g_telnetClient = g_telnetServer.available();
      g_telnetClient.println("=== ESP32-CAM serial mirror ===");
    }
  }
  if (g_telnetClient && !g_telnetClient.connected()) g_telnetClient.stop();
}

// آخر عنوان انطلقت عليه الخدمات.
//
// **الخدمات كانت بتنطلق مرّة وحدة للأبد.** واللوح ممكن يغيّر شبكته — من
// التطبيق، أو لأنّ الراوتر رجّع توزيع العناوين — فياخد عنوانًا جديد. وقتها
// مقبس التلنت وخادم الترقية بيضلّوا مربوطين ع عنوان ما عاد إله وجود: اللوح
// شغّال وبينبض وبيصوّر، وما حدا بيقدر يوصله.
//
// وهاد بيبيّن «خلل بالمراقبة» وهو مش خلل بالمراقبة — هو خدمة ما انولدت من
// جديد بعد ما تغيّر البيت.
static IPAddress g_servicesIp;

void startNetworkServicesIfReady() {
  if (WiFi.status() != WL_CONNECTED) return;

  IPAddress now = WiFi.localIP();
  if (g_networkServicesStarted && now == g_servicesIp) return;

  if (g_networkServicesStarted) {
    g_log.printf("[NET] العنوان تغيّر %s ← %s — بنعيد تشغيل الخدمات\n",
                 g_servicesIp.toString().c_str(), now.toString().c_str());
    // نقفل التلنت القديم صراحة: المقبس المربوط ع عنوان راح بيضلّ ماسك المنفذ،
    // والربط الجديد بيفشل بصمت.
    if (g_telnetClient) g_telnetClient.stop();
    g_telnetServer.stop();
  }

  setupOTA();
  setupTelnet();
  setupMQTT();
  g_servicesIp = now;
  g_networkServicesStarted = true;
}
