#ifndef ROOM_SECRETS_H
#define ROOM_SECRETS_H

// انسخ هذا الملف إلى secrets.h وعبّئ القيم. لا ترفع secrets.h إلى Git.
// نفس بروكر HiveMQ ونفس الواي فاي تبع الروبوت — الروم-نود جهاز ثانٍ عليه.
// استخدم Wi-Fi 2.4GHz فقط.
// **هالقيم بتنكتب بذاكرة اللوح أوّل حرق بالكيبل** (sandy_identity.h)، وبعدها
// اللوح بيعيش عليها. صورة التحديث عن بعد بتنبنى من هالملف المثال نفسه، فما
// فيها ولا سرّ — وقيمة مثال (YOUR_… أو XXXX) ما بتمسح قيمة محفوظة أبدًا.

const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// بيانات دخول خاصة بهالعقدة، مش نسخة عن تبع الدماغ ولا الكاميرا — العقدة ما
// إلها وصلة صوت تاخد منها مفتاحها، فبياخده من هون وقت الحرق.
// التفصيل: docs/مفاتيح-الوسيط.md
#define SANDY_MQTT_HOST "YOUR_HIVEMQ_HOST.s1.eu.hivemq.cloud"
#define SANDY_MQTT_PORT 8883
#define SANDY_MQTT_USER "YOUR_MQTT_USER"
#define SANDY_MQTT_PASS "YOUR_MQTT_PASS"

// نسخة التطوير: ترقية ع الشبكة المحلية. **لا تفعّلها بنسخة بتنباع** — بالبيع
// التحديث بينزل موقّع من الخادم (sandy_ota_pull.h).
// #define SANDY_DEV 1
// #define SANDY_OTA_PASSWORD "YOUR_OTA_PASSWORD"

// خادم ساندي، للتحديثات. الافتراضي بـ room-node.ino.
// #define SANDY_API_HOST "your-app.herokuapp.com"

// كود الاقتران المطبوع ع علبة الروبوت — **نفس الكود المحروق ع الدماغ
// والكاميرا**. عقدة الغرفة بتشتق منه شجرتها: `sandy/node/<معرّف>/room/…`.
// كود مختلف معناه العقدة بتسمع ع شجرة تانية، والأوامر بتضيع بلا أي خطأ.
// اللوح ما بيترجم بالكود المثال.
#define SANDY_PAIR_CODE     "SANDY-XXXX"

#endif
