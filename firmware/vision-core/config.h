#ifndef SANDY_ESP32CAM_CONFIG_H
#define SANDY_ESP32CAM_CONFIG_H

// هون مش بالـino: Arduino بيولّد تعريفات الدوال بالملف الرئيسي وبيحتاج httpd_req_t.
#include "esp_http_server.h"

// ===== AI Thinker ESP32-CAM pins =====
#ifndef PWDN_GPIO_NUM
  #define PWDN_GPIO_NUM 32
#endif
#ifndef RESET_GPIO_NUM
  #define RESET_GPIO_NUM -1
#endif
#ifndef XCLK_GPIO_NUM
  #define XCLK_GPIO_NUM 0
#endif
#ifndef SIOD_GPIO_NUM
  #define SIOD_GPIO_NUM 26
#endif
#ifndef SIOC_GPIO_NUM
  #define SIOC_GPIO_NUM 27
#endif
#ifndef Y9_GPIO_NUM
  #define Y9_GPIO_NUM 35
#endif
#ifndef Y8_GPIO_NUM
  #define Y8_GPIO_NUM 34
#endif
#ifndef Y7_GPIO_NUM
  #define Y7_GPIO_NUM 39
#endif
#ifndef Y6_GPIO_NUM
  #define Y6_GPIO_NUM 36
#endif
#ifndef Y5_GPIO_NUM
  #define Y5_GPIO_NUM 21
#endif
#ifndef Y4_GPIO_NUM
  #define Y4_GPIO_NUM 19
#endif
#ifndef Y3_GPIO_NUM
  #define Y3_GPIO_NUM 18
#endif
#ifndef Y2_GPIO_NUM
  #define Y2_GPIO_NUM 5
#endif
#ifndef VSYNC_GPIO_NUM
  #define VSYNC_GPIO_NUM 25
#endif
#ifndef HREF_GPIO_NUM
  #define HREF_GPIO_NUM 23
#endif
#ifndef PCLK_GPIO_NUM
  #define PCLK_GPIO_NUM 22
#endif

// نسخة التطوير: ترقية محلية + مرآة السجل ع التلنت. زي الروبوت: شغّالة لحالها لمّا
// secrets.h فيه كلمة سر الترقية، ونسخة البيع (`SANDY_RETAIL`، من ملف النشر) بتسكّرها.
#ifndef SANDY_DEV
  #if defined(SANDY_OTA_PASSWORD) && !(defined(SANDY_RETAIL) && SANDY_RETAIL)
    #define SANDY_DEV 1
  #else
    #define SANDY_DEV 0
  #endif
#endif

#define CAMERA_SERIAL_BAUD 115200
#define CAMERA_BOOT_DELAY_MS 500
#define CAMERA_WIFI_POLL_DELAY_MS 500
#define CAMERA_XCLK_FREQ_HZ 20000000

// دقّة متوسطة عند الإقلاع: مخازن المستشعر بالذاكرة الداخلية بتكبر مع الدقّة،
// وبـ UXGA ما ضلّ مكان لمصافحة TLS مع الوسيط (SSL - Memory allocation failed).
#define CAMERA_DEFAULT_FRAME_SIZE FRAMESIZE_VGA   // 640x480
// وهي كمان الحدّ الأعلى: مخزن الإطار بيتحجز مرّة وحدة ع قدّ هالدقّة وما بيكبر.
#define CAMERA_MAX_FRAME_SIZE     CAMERA_DEFAULT_FRAME_SIZE
#define CAMERA_DEFAULT_JPEG_QUALITY 12             // 10-15 جيد، أقل = أعلى جودة + حجم أكبر
#define CAMERA_DEFAULT_FB_COUNT 1
#define CAMERA_VERTICAL_FLIP 1

// MQTT — نفس وسيط Sandy
#define MQTT_RECONNECT_INTERVAL_MS  5000
#define STATUS_POST_INTERVAL_MS     10000           // كل 10s حالة
#define WIFI_RECONNECT_INTERVAL_MS  10000

// الصور ما بتمرق بالوسيط، فالمخزن للأوامر والحالة (أكبرها ~ألف بايت).
#define MQTT_BUFFER_SIZE            1536

// البثّ البعيد: إطار كل تلت ثانية؛ أسرع بيبطّئ الأوامر والنبضة.
#define CAM_REMOTE_STREAM_INTERVAL_MS 330

// البثّ البعيد بيوقف لحاله بعد خمس دقايق لو حدا نسيه.
#define CAM_REMOTE_STREAM_MAX_MS   (5UL * 60UL * 1000UL)

// OTA المحلية (نسخة التطوير بس)
#define SANDY_OTA_HOSTNAME "sandy-esp32cam"

// الخادم ومفتاح الرفع المشترك (القيمة الحقيقية بـ secrets.h وبعدها بذاكرة اللوح).
#ifndef SANDY_UPLOAD_HOST
  #define SANDY_UPLOAD_HOST "sandy-robot-3da0693d32f7.herokuapp.com"
#endif
#ifndef SANDY_WS_HMAC_KEY
  #define SANDY_WS_HMAC_KEY ""
#endif

// ===== Topics =====
// تحت sandy/node/<معرّف>/cam/... ؛ الكاميرا بتنحرق بنفس كود الاقتران تبع الروبوت،
// فبتصير مخارج ع نفس العقدة. الاشتقاق لازم يطابق node_store.code_to_node_id.
#define SANDY_TOPIC_ROOT    "sandy/node/"
#define TOPIC_SUFFIX_REQUEST   "/cam/request"
#define TOPIC_SUFFIX_COMMAND   "/cam/command"
#define TOPIC_SUFFIX_SNAPSHOT  "/cam/snapshot"
#define TOPIC_SUFFIX_STATUS    "/cam/status"
#define TOPIC_SUFFIX_EVENT     "/cam/event"
#define TOPIC_SUFFIX_WIFI      "/cam/wifi"

// ===== Flash LED (AI-Thinker on-board white LED) =====
// قوية، فبنتحكّم بشدّتها بـ PWM ومع مؤقت أمان.
#define FLASH_LED_GPIO            4
#define FLASH_PWM_CHANNEL         7      // ch0 محجوزة لساعة الكاميرا (XCLK)
#define FLASH_PWM_FREQ_HZ         5000
#define FLASH_PWM_BITS            8
#define FLASH_DEFAULT_LEVEL       160    // من 0 لـ 255
#define FLASH_WARMUP_MS           120    // تشتعل قبل الالتقاط بهالمدة
#define FLASH_MAX_ON_MS           8000   // أمان: ما تضل شغالة أكتر من هيك
#define FLASH_AUTO_GAIN_THRESHOLD 20     // كسب المستشعر أعلى من هيك = عتمة
#define FLASH_AUTO_GAIN_REG_THRESHOLD 0x30  // سجلّ الكسب الحيّ بـ OV2640: ×٤ وطالع

// ===== HTTP (still + MJPEG video stream) =====
// الفيديو ما بيمشي عبر MQTT، فخادم صور مباشر.
// اسم اللوح ونسخته بكل نبضة، عشان نعرف أي لوح هاد.
#define SANDY_CAM_BOARD_ID        "sandy-cam"
#define SANDY_CAM_FW_VERSION      "0.4.1"

#define CAM_HTTP_PORT             80
// مفتاح البث المحلي: الفاضي معناه «مفتاح عشوائي كل إقلاع» (بيوصل التطبيق عبر الخادم)، مش «بلا حماية».
#ifndef CAM_HTTP_TOKEN
  #define CAM_HTTP_TOKEN ""
#endif
#define CAM_STREAM_IDLE_TIMEOUT_MS 120000  // بث بلا متفرّج → يوقف لحاله
// أطول جلسة مشاهدة محلية، نفس سقف البعيد.
#define CAM_LOCAL_STREAM_MAX_MS   (5UL * 60UL * 1000UL)
// أقلّ فاصل بين طلبات التصوير والبث (حرارة الفلاش والإغراق).
#define CAM_COMMAND_MIN_GAP_MS    1500

// ===== Burst / panorama =====
// الدماغ بيلف الرقبة والكاميرا بتصوّر لقطة كل زاوية.
#define BURST_MAX_FRAMES          24
#define BURST_MIN_INTERVAL_MS     200
#define CAPTURE_MAX_SETTLE_MS     3000   // انتظار ثبات الصورة بعد الحركة

// ===== Settings persistence =====
#define SETTINGS_NVS_NAMESPACE    "sandycam"

// وضع الفلاش وقت الالتقاط.
enum FlashMode { FLASH_MODE_OFF = 0, FLASH_MODE_ON = 1, FLASH_MODE_AUTO = 2 };

#endif
