#pragma once
// Copy this file to secrets.h and fill in your values.
// secrets.h is gitignored — never commit it.

#define WIFI_SSID           "YOUR_WIFI_SSID"
#define WIFI_PASS           "YOUR_WIFI_PASSWORD"

// HiveMQ Cloud — format: mqtts://xxxx.s1.eu.hivemq.cloud:8883
#define MQTT_BROKER_URI     "mqtts://YOUR_BROKER.hivemq.cloud:8883"
// آخر مفتاح مشترك: بس للإقلاع الأول، قبل ما اللوح ياخد مفتاحه الخاص من مصافحة
// الصوت ويحفظه بذاكرته. بعدها المحفوظ هو المستعمل، والمكتوب هون ما بينقرا.
// انظر docs/مفاتيح-الوسيط.md
#define MQTT_USER           "YOUR_MQTT_USER"
#define MQTT_PASS           "YOUR_MQTT_PASS"

// Voice link to the cloud (/voice). The HMAC key must match the server's
// SANDY_WS_HMAC_KEY config var.
#define SANDY_VOICE_WS_URI  "wss://YOUR_APP.herokuapp.com/voice"
#define SANDY_WS_HMAC_KEY   "YOUR_WS_HMAC_KEY"
// **يجب أن يساوي معرّف الوحدة** — أي `SANDY_PAIR_CODE` تحت، بحروف صغيرة
// وأرقام فقط. ليس اسم موديل.
//
// المقبس الصوتي يأخذ هذه القيمة ويسأل بها: «من يملك هذه الوحدة؟» — ليعرف ذاكرة
// من يفتح. واسم الموديل ليس وحدة، فالبحث يرجع فارغًا، وكانت النتيجة أنّ ساندي
// تحدّثت مع مالكها الجديد وهي تحمل ذاكرة المالك القديم: نادته باسمه، وعدّدت
// عليه مهامه.
//
// The device id must equal the node id. A model name here makes every voice
// session anonymous, and anonymous sessions used to inherit somebody else's
// memory.
#define SANDY_DEVICE_ID     "sandy0001"

// The pairing code printed on this robot's box — the one its owner types into
// the app once. The firmware derives its MQTT topics from it (lowercase,
// alphanumerics only), so every robot answers only on its own tree:
//   sandy/node/<derived>/mood, /servo, /volume, …
// Unique per unit. Two robots sharing a code would obey each other's owner.
#define SANDY_PAIR_CODE     "SANDY-0001"
