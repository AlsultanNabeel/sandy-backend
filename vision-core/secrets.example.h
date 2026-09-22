#ifndef SANDY_ESP32CAM_SECRETS_H
#define SANDY_ESP32CAM_SECRETS_H

// انسخ هالملف لـ secrets.h وعبّي القيم. secrets.h مستبعد من المستودع.

// WiFi — الشبكة الأولى. بعد الإعداد الكاميرا بتحفظ شبكة المالك وبتستعملها.
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

// كود الاقتران المطبوع ع علبة الروبوت — نفس الكود المحروق ع عقل الروبوت.
// الكاميرا بتشتق منه نفس المعرّف، فبتصير مخارج زيادة ع نفس العقدة بدل ما تكون
// جهاز تاني الزبون لازم يقرنه لحاله.
#define SANDY_PAIR_CODE     "SANDY-XXXX"

// رفع الصور: مفتاح التوقيع (نفس مفتاح مقبس الصوت عند الخادم) وعنوان الخادم.
// بلا المفتاح الرفع معطّل، يعني لا صور ولا بث بعيد.
#define SANDY_WS_HMAC_KEY   "YOUR_SHARED_UPLOAD_KEY"
// #define SANDY_UPLOAD_HOST "your-app.herokuapp.com"   // الافتراضي بـ cam_upload.ino

// مفتاح البث المحلي. اتركه معلّقًا: الكاميرا بتولّد مفتاحًا عشوائيًّا كل إقلاع
// وبتعطيه للخادم، والخادم بيعطيه لصاحب الروبوت بس.
// #define CAM_HTTP_TOKEN "..."

// نسخة التطوير: ترقية ع الشبكة المحلية + مرآة السجل ع التلنت. **لا تفعّلها
// بنسخة بتنباع.**
// #define SANDY_DEV 1
// #define SANDY_OTA_PASSWORD "YOUR_OTA_PASSWORD"

#endif
