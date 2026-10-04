#ifndef ROOM_SECRETS_H
#define ROOM_SECRETS_H

// انسخه لـ secrets.h (ما بينرفع ع Git). Wi-Fi 2.4GHz بس.
// القيم بتنكتب بذاكرة اللوح أوّل حرق بالكيبل (sandy_identity.h)؛ صورة التحديث بتنبنى
// من هالملف، وقيمة مثال ما بتمسح المحفوظ.

const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

// بيانات دخول خاصة بالعقدة (ما إلها وصلة صوت تاخد منها مفتاح). docs/مفاتيح-الوسيط.md
#define SANDY_MQTT_HOST "YOUR_HIVEMQ_HOST.s1.eu.hivemq.cloud"
#define SANDY_MQTT_PORT 8883
#define SANDY_MQTT_USER "YOUR_MQTT_USER"
#define SANDY_MQTT_PASS "YOUR_MQTT_PASS"

// نسخة التطوير (ترقية ع الشبكة المحلية): بتشتغل لحالها لمّا تحط كلمة السر هون.
// ملف النشر بيبني بلاها، فنسخة البيع بتطلع بلا ترقية محلية.
// #define SANDY_OTA_PASSWORD "YOUR_OTA_PASSWORD"

// خادم ساندي للتحديثات (الافتراضي بـ room-node.ino).
// #define SANDY_API_HOST "your-app.herokuapp.com"

// كود الاقتران ع العلبة: نفس كود الدماغ والكاميرا، وإلا الأوامر بتضيع بصمت.
// ما بيترجم بالكود المثال.
#define SANDY_PAIR_CODE     "SANDY-XXXX"

#endif
