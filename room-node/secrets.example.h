#ifndef ROOM_SECRETS_H
#define ROOM_SECRETS_H

// انسخ هذا الملف إلى secrets.h وعبّئ القيم. لا ترفع secrets.h إلى Git.
// نفس بروكر HiveMQ ونفس الواي فاي تبع الروبوت — الروم-نود جهاز ثانٍ عليه.
// استخدم Wi-Fi 2.4GHz فقط.

const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// بيانات دخول خاصة بهالعقدة، مش نسخة عن تبع الدماغ ولا الكاميرا — العقدة ما
// إلها وصلة صوت تاخد منها مفتاحها، فبياخده من هون وقت الحرق.
// التفصيل: docs/مفاتيح-الوسيط.md
#define SANDY_MQTT_HOST "YOUR_HIVEMQ_HOST.s1.eu.hivemq.cloud"
#define SANDY_MQTT_PORT 8883
#define SANDY_MQTT_USER "YOUR_MQTT_USER"
#define SANDY_MQTT_PASS "YOUR_MQTT_PASS"

#define SANDY_OTA_PASSWORD "sandy-ota"

// كود الاقتران المطبوع ع علبة الروبوت — **نفس الكود المحروق ع الدماغ
// والكاميرا**. عقدة الغرفة بتشتق منه شجرتها: `sandy/node/<معرّف>/room/…`.
// كود مختلف معناه العقدة بتسمع ع شجرة تانية، والأوامر بتضيع بلا أي خطأ.
#define SANDY_PAIR_CODE     "SANDY-0001"

#endif
