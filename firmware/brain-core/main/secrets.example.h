#pragma once
// Copy to secrets.h (gitignored) and fill in. Saved to NVS on the first cable-flash
// boot. The retail OTA build compiles this file instead, so images carry no secrets;
// placeholders ("YOUR_…", "…XXXX…", empty) never overwrite a saved value.

#define WIFI_SSID           "YOUR_WIFI_SSID"
#define WIFI_PASS           "YOUR_WIFI_PASSWORD"

// Format: mqtts://xxxx.s1.eu.hivemq.cloud:8883
#define MQTT_BROKER_URI     "mqtts://YOUR_BROKER.hivemq.cloud:8883"
// للإقلاع الأول فقط، بعدها اللوح بيستعمل مفتاحه الخاص من مصافحة الصوت.
#define MQTT_USER           "YOUR_MQTT_USER"
#define MQTT_PASS           "YOUR_MQTT_PASS"

// The HMAC key must match the server's SANDY_WS_HMAC_KEY.
#define SANDY_VOICE_WS_URI  "wss://YOUR_APP.herokuapp.com/voice"
#define SANDY_WS_HMAC_KEY   "YOUR_WS_HMAC_KEY"
// يجب أن يساوي معرّف الوحدة (SANDY_PAIR_CODE بحروف صغيرة)، لا اسم موديل.
// Leave empty to derive it from SANDY_PAIR_CODE; a wrong id makes voice sessions anonymous.
#define SANDY_DEVICE_ID     ""

// The code on the box; MQTT topics derive from it (lowercase alphanumerics).
// Must be unique per unit.
#define SANDY_PAIR_CODE     "SANDY-XXXX"
