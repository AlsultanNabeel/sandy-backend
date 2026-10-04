// ESP32-CAM — OTA + Telnet (نسخة التطوير بس: الترقية المحلية بلا توقيع والتلنت بلا كلمة سر).

#if SANDY_DEV
#ifndef SANDY_OTA_PASSWORD
  #error "SANDY_DEV needs SANDY_OTA_PASSWORD in secrets.h"
#endif
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
      WiFiClient n = g_telnetServer.accept();
      n.println("[TELNET] busy"); n.stop();
    } else {
      g_telnetClient = g_telnetServer.accept();
      g_telnetClient.println("=== ESP32-CAM serial mirror ===");
    }
  }
  if (g_telnetClient && !g_telnetClient.connected()) g_telnetClient.stop();
}
#endif  // SANDY_DEV

// آخر عنوان انطلقت عليه الخدمات؛ منعيد إطلاقها لمّا يتغيّر العنوان.
static IPAddress g_servicesIp;

void camSyncClock();

void startNetworkServicesIfReady() {
  if (WiFi.status() != WL_CONNECTED) return;

  IPAddress now = WiFi.localIP();
  if (g_networkServicesStarted && now == g_servicesIp) return;

  if (g_networkServicesStarted) {
    g_log.printf("[NET] العنوان تغيّر %s ← %s — بنعيد تشغيل الخدمات\n",
                 g_servicesIp.toString().c_str(), now.toString().c_str());
#if SANDY_DEV
    // سكّر التلنت القديم، وإلا الربط الجديد بيفشل بصمت.
    if (g_telnetClient) g_telnetClient.stop();
    g_telnetServer.stop();
#endif
  }

#if SANDY_DEV
  setupOTA();
  setupTelnet();
#endif
  setupMQTT();
  // الساعة مع الخدمات، مش عند أول صورة.
  camSyncClock();
  g_servicesIp = now;
  g_networkServicesStarted = true;
}
