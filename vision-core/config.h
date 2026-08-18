#ifndef SANDY_ESP32CAM_CONFIG_H
#define SANDY_ESP32CAM_CONFIG_H

// لازم يكون هون مش بملف الـino: Arduino بيولّد تعريفات الدوال تلقائياً وبيحطها
// بالملف الرئيسي، فلو نوع httpd_req_t مش معروف لهناك بتفشل الترجمة.
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

#define CAMERA_SERIAL_BAUD 115200
#define CAMERA_BOOT_DELAY_MS 500
#define CAMERA_WIFI_POLL_DELAY_MS 500
#define CAMERA_XCLK_FREQ_HZ 20000000

#define CAMERA_DEFAULT_FRAME_SIZE FRAMESIZE_VGA   // 640x480 — توازن جودة/حجم لـ Vision API
#define CAMERA_DEFAULT_JPEG_QUALITY 12             // 10-15 جيد، أقل = أعلى جودة + حجم أكبر
#define CAMERA_DEFAULT_FB_COUNT 1
#define CAMERA_VERTICAL_FLIP 1

// MQTT — نفس HiveMQ تبع Sandy
#define MQTT_RECONNECT_INTERVAL_MS  5000
#define STATUS_POST_INTERVAL_MS     10000           // كل 10s حالة
#define WIFI_RECONNECT_INTERVAL_MS  10000

// إرسال الصور: chunked publish — حجم صغير لتجنّب stack overflow في TLS write
#define SNAPSHOT_CHUNK_RAW_BYTES    1024            // 1KB raw → ~1.4KB base64
#define MQTT_BUFFER_SIZE            2048            // يكفي لـ chunk + JSON overhead
#define SNAPSHOT_INTER_CHUNK_DELAY_MS 5             // فاصل خفيف بين الـ chunks

// OTA
#define SANDY_OTA_HOSTNAME "sandy-esp32cam"

// ===== Topics =====
// المواضيع صارت تحت اسم الروبوت مش عامة: sandy/node/<كود>/cam/...
//
// كانت "sandy/cam/snapshot" وأخواتها — بتشتغل تمام طول ما في روبوت واحد بالعالم.
// تنين ع نفس الوسيط، وكل كاميرا بترد ع طلب صاحب التاني. وهاي مش علة بتلاقيها
// بالتجريب، هاي علة بيلاقيها تاني زبون.
//
// كرت الكاميرا بيجي بنفس علبة الروبوت وبينحرق بنفس كود الاقتران، فبيطلّع نفس
// المعرّف. يعني روبوت واحد = عقدة وحدة، والكاميرا مخارج زيادة عليها — مش إشي
// تاني لازم الزبون يقرنه لحاله.
//
// الاشتقاق لازم يطابق node_store.code_to_node_id بالخادم: حروف صغيرة، وأرقام
// وحروف بس. لو اختلف طرف عن التاني، الكاميرا بتسكت وما في إشي بيقول ليش.
#define SANDY_TOPIC_ROOT    "sandy/node/"
#define TOPIC_SUFFIX_REQUEST   "/cam/request"
#define TOPIC_SUFFIX_COMMAND   "/cam/command"
#define TOPIC_SUFFIX_SNAPSHOT  "/cam/snapshot"
#define TOPIC_SUFFIX_STATUS    "/cam/status"
#define TOPIC_SUFFIX_EVENT     "/cam/event"
#define TOPIC_SUFFIX_WIFI      "/cam/wifi"

// ===== Flash LED (AI-Thinker on-board white LED) =====
// اللمبة البيضا اللي على ظهر اللوحة. قوية جداً، فمنشغّلها بنبضة عرض (PWM)
// عشان نتحكم بشدتها، ومع مؤقت أمان يطفيها لحاله.
#define FLASH_LED_GPIO            4
#define FLASH_PWM_CHANNEL         7      // ch0 محجوزة لساعة الكاميرا (XCLK)
#define FLASH_PWM_FREQ_HZ         5000
#define FLASH_PWM_BITS            8
#define FLASH_DEFAULT_LEVEL       160    // من 0 لـ 255
#define FLASH_WARMUP_MS           120    // تشتعل قبل الالتقاط بهالمدة
#define FLASH_MAX_ON_MS           8000   // أمان: ما تضل شغالة أكتر من هيك
#define FLASH_AUTO_GAIN_THRESHOLD 20     // كسب المستشعر أعلى من هيك = عتمة

// ===== HTTP (still + MJPEG video stream) =====
// الفيديو ما بينفع عبر MQTT (بطيء وبيخنق البروكر)، فمنعمل خادم صور مباشر.
// اسم اللوح ونسخته — بيروحوا بكل نبضة.
//
// تلات ألواح إسبريسيف ع نفس الشبكة وتلات ملفات مختلفة ما بتتبادل. بلا اسم صريح
// بالنبضة، «وين الكاميرا؟» بينجاوب بمسح الشبكة وتخمين — وهاد صار فعلًا.
#define SANDY_CAM_BOARD_ID        "sandy-cam"
#define SANDY_CAM_FW_VERSION      "0.3.0"

#define CAM_HTTP_PORT             80
#ifndef CAM_HTTP_TOKEN
  #define CAM_HTTP_TOKEN ""              // فاضي = بلا حماية (شبكة محلية فقط)
#endif
#define CAM_STREAM_IDLE_TIMEOUT_MS 120000  // بث بلا متفرّج → يوقف لحاله

// ===== Burst / panorama =====
// البانوراما: الدماغ بيلف الرقبة والكاميرا بتصوّر لقطة كل زاوية.
#define BURST_MAX_FRAMES          24
#define BURST_MIN_INTERVAL_MS     200
#define CAPTURE_MAX_SETTLE_MS     3000   // انتظار ثبات الصورة بعد الحركة

// ===== Settings persistence =====
#define SETTINGS_NVS_NAMESPACE    "sandycam"

// وضع الفلاش وقت الالتقاط: مطفي دايماً، مشعول دايماً، أو حسب إضاءة المكان.
enum FlashMode { FLASH_MODE_OFF = 0, FLASH_MODE_ON = 1, FLASH_MODE_AUTO = 2 };

#endif
