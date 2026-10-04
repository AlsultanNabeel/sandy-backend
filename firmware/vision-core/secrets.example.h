#ifndef SANDY_ESP32CAM_SECRETS_H
#define SANDY_ESP32CAM_SECRETS_H

// انسخه لـ secrets.h (مستبعد من المستودع). القيم بتنكتب بذاكرة اللوح أوّل حرق بالكيبل
// (sandy_identity.h)؛ صورة التحديث بتنبنى من هالملف، وقيمة مثال ما بتمسح المحفوظ.

// الشبكة الأولى؛ بعد الإعداد بتحفظ شبكة المالك.
#define SECRET_SSID "YOUR_WIFI_SSID"
#define SECRET_OPTIONAL_PASS "YOUR_WIFI_PASSWORD"

// MQTT: بيانات دخول خاصة بالكاميرا (ما إلها وصلة صوت تاخد منها مفتاح). docs/مفاتيح-الوسيط.md
#define SANDY_MQTT_HOST "YOUR_HIVEMQ_HOST.s1.eu.hivemq.cloud"
#define SANDY_MQTT_PORT 8883
#define SANDY_MQTT_USER "YOUR_MQTT_USER"
#define SANDY_MQTT_PASS "YOUR_MQTT_PASSWORD"

// كود الاقتران ع العلبة، نفس كود الدماغ، فالكاميرا بتصير مخارج ع نفس العقدة.
#define SANDY_PAIR_CODE     "SANDY-XXXX"

// مفتاح توقيع الرفع (نفس مفتاح مقبس الصوت بالخادم). بلاه لا صور ولا بث بعيد.
#define SANDY_WS_HMAC_KEY   "YOUR_SHARED_UPLOAD_KEY"
// #define SANDY_UPLOAD_HOST "your-app.herokuapp.com"   // الافتراضي بـ cam_upload.ino

// مفتاح البث المحلي: اتركه معلّق، الكاميرا بتولّد واحد عشوائي كل إقلاع.
// #define CAM_HTTP_TOKEN "..."

// نسخة التطوير (ترقية محلية + مرآة السجل ع التلنت): بتشتغل لحالها لمّا تحط كلمة السر هون.
// ملف النشر بيبني بلاها، فنسخة البيع بتطلع بلا ترقية محلية.
// #define SANDY_OTA_PASSWORD "YOUR_OTA_PASSWORD"

#endif
