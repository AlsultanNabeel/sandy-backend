#pragma once
// Copy this file to secrets.h and fill in your values.
// secrets.h is gitignored — never commit it.

#define WIFI_SSID           "YOUR_WIFI_SSID"
#define WIFI_PASS           "YOUR_WIFI_PASSWORD"

// HiveMQ Cloud — format: mqtts://xxxx.s1.eu.hivemq.cloud:8883
#define MQTT_BROKER_URI     "mqtts://YOUR_BROKER.hivemq.cloud:8883"
#define MQTT_CLIENT_ID      "sandy-brain-s3"
#define MQTT_USER           "YOUR_MQTT_USER"
#define MQTT_PASS           "YOUR_MQTT_PASS"

// Voice link to the cloud (/voice). The HMAC key must match the server's
// SANDY_WS_HMAC_KEY config var.
#define SANDY_VOICE_WS_URI  "wss://YOUR_APP.herokuapp.com/voice"
#define SANDY_WS_HMAC_KEY   "YOUR_WS_HMAC_KEY"
#define SANDY_DEVICE_ID     "sandy-brain-s3"

// The pairing code printed on this robot's box — the one its owner types into
// the app once. The firmware derives its MQTT topics from it (lowercase,
// alphanumerics only), so every robot answers only on its own tree:
//   sandy/node/<derived>/mood, /servo, /volume, …
// Unique per unit. Two robots sharing a code would obey each other's owner.
#define SANDY_PAIR_CODE     "SANDY-0001"
