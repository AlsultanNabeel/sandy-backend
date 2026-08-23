#ifndef SANDY_ESP32CAM_SECRETS_H
#define SANDY_ESP32CAM_SECRETS_H

// WiFi
#define SECRET_SSID "YOUR_WIFI_SSID"
#define SECRET_OPTIONAL_PASS "YOUR_WIFI_PASSWORD"

// MQTT (HiveMQ Cloud) — نفس الوسيط تبع ساندي.
//
// **بيانات دخول خاصة بهالكاميرا، مش نسخة عن تبع الدماغ.** الكاميرا ما إلها
// وصلة صوت، فما بتقدر تاخد مفتاحها من الخادم زي الدماغ — بياخده من هون وقت
// الحرق. مفتاح واحد ع كل القطع بيرجّع نفس الثغرة: زبون بيسمع مواضيع زبون تاني.
// التفصيل: docs/مفاتيح-الوسيط.md
#define SANDY_MQTT_HOST "YOUR_HIVEMQ_HOST.s1.eu.hivemq.cloud"
#define SANDY_MQTT_PORT 8883
#define SANDY_MQTT_USER "YOUR_MQTT_USER"
#define SANDY_MQTT_PASS "YOUR_MQTT_PASSWORD"

// OTA
#define SANDY_OTA_PASSWORD "YOUR_OTA_PASSWORD"

#endif

// كود الاقتران المطبوع ع علبة الروبوت — نفس الكود المحروق ع عقل الروبوت.
// الكاميرا بتشتق منه نفس المعرّف، فبتصير مخارج زيادة ع نفس العقدة بدل ما تكون
// جهاز تاني الزبون لازم يقرنه لحاله.
#define SANDY_PAIR_CODE     "SANDY-0001"
