// =========================
// ESP32-CAM — Camera Init + Snapshot Capture + Upload
// =========================
// التقاط: VGA 640x480 JPEG quality=12 → عادة 40-80KB، وبترتفع بطلب واحد للخادم.

// ── إعلانات من ملفات تانية ──
void mqttPublishEvent(const char* json);
void settingsLoadFromNvs();
bool camLock(uint32_t waitMs);
void camUnlock();
void camWait(unsigned long ms);
bool uploadSnapshot(const String& id, const uint8_t* data, size_t len);
bool flashWantedForCapture(FlashMode mode);
void flashSet(uint8_t level, unsigned long autoOffMs);
void flashOff();

static camera_config_t buildCameraConfig() {
  camera_config_t cfg = {};
  cfg.ledc_channel = LEDC_CHANNEL_0;
  cfg.ledc_timer = LEDC_TIMER_0;
  cfg.pin_d0 = Y2_GPIO_NUM;
  cfg.pin_d1 = Y3_GPIO_NUM;
  cfg.pin_d2 = Y4_GPIO_NUM;
  cfg.pin_d3 = Y5_GPIO_NUM;
  cfg.pin_d4 = Y6_GPIO_NUM;
  cfg.pin_d5 = Y7_GPIO_NUM;
  cfg.pin_d6 = Y8_GPIO_NUM;
  cfg.pin_d7 = Y9_GPIO_NUM;
  cfg.pin_xclk = XCLK_GPIO_NUM;
  cfg.pin_pclk = PCLK_GPIO_NUM;
  cfg.pin_vsync = VSYNC_GPIO_NUM;
  cfg.pin_href = HREF_GPIO_NUM;
  cfg.pin_sccb_sda = SIOD_GPIO_NUM;
  cfg.pin_sccb_scl = SIOC_GPIO_NUM;
  cfg.pin_pwdn = PWDN_GPIO_NUM;
  cfg.pin_reset = RESET_GPIO_NUM;
  cfg.xclk_freq_hz = CAMERA_XCLK_FREQ_HZ;
  cfg.pixel_format = PIXFORMAT_JPEG;
  cfg.frame_size = CAMERA_DEFAULT_FRAME_SIZE;
  cfg.jpeg_quality = CAMERA_DEFAULT_JPEG_QUALITY;
  cfg.fb_count = CAMERA_DEFAULT_FB_COUNT;
  cfg.grab_mode = CAMERA_GRAB_WHEN_EMPTY;
  cfg.fb_location = psramFound() ? CAMERA_FB_IN_PSRAM : CAMERA_FB_IN_DRAM;

  // بلا ذاكرة خارجية ما في مجال للدقّة الكاملة — المخزن الداخلي ما بيسعها،
  // والتشغيل بيفشل من أصله. فبننزل لدقّة بتشتغل بدل ما نموت بالإقلاع.
  if (!psramFound()) {
    cfg.frame_size = FRAMESIZE_SVGA;
    cfg.jpeg_quality = 15;
  }
  return cfg;
}

void setupCamera() {
  pinMode(PWDN_GPIO_NUM, OUTPUT);

  // دورة باور كاملة: مطفي ثم مشغّل — يساعد إذا الكام في حالة معلّقة
  digitalWrite(PWDN_GPIO_NUM, HIGH);  // power down
  delay(100);
  digitalWrite(PWDN_GPIO_NUM, LOW);   // power up
  delay(200);

  camera_config_t cfg = buildCameraConfig();

  // محاولة أولى
  esp_err_t err = esp_camera_init(&cfg);
  if (err != ESP_OK) {
    g_log.printf("[CAM] init attempt 1 failed: 0x%x — retrying...\n", err);
    esp_camera_deinit();
    digitalWrite(PWDN_GPIO_NUM, HIGH);
    delay(300);
    digitalWrite(PWDN_GPIO_NUM, LOW);
    delay(300);
    err = esp_camera_init(&cfg);
  }

  if (err != ESP_OK) {
    g_log.printf("[CAM] init FAILED: 0x%x — check ribbon + power 5V/1A+\n", err);
    g_cameraReady = false;
    return;
  }

  sensor_t* s = esp_camera_sensor_get();
  if (s) s->set_vflip(s, CAMERA_VERTICAL_FLIP);

  g_cameraReady = true;
  g_log.println("[CAM] ✅ camera ready");
}

void captureAndPublishSnapshot(const String& id, unsigned int settleMs, FlashMode flash) {
  char ev[160];
  if (!g_cameraReady) {
    // لا نحاول re-init هنا — esp_camera_init() ممكن يعلّق إذا الهاردوير مش راد
    // (ribbon غير مثبت، باور ناقص). نرسل خطأ فوراً بدل ما نهنّق الـ loop.
    g_log.println("[CAM] not ready — sending error without re-init");
    snprintf(ev, sizeof(ev),
             "{\"id\":\"%s\",\"error\":\"camera_init_failed_at_boot\"}", id.c_str());
    mqttPublishEvent(ev);
    return;
  }

  // انتظار ثبات: بعد ما تلف الرقبة، أول إطار بيطلع مهزوز والتعريض لسا ما ضبط
  if (settleMs > 0) camWait(settleMs);

  // **المستشعر إلنا لحدّ ما نخلص** — بما فيه الإنعاش تحت. بلا القفل، الإنعاش
  // بيعمل `deinit` وخادم البث المحلي ماسك إطارًا، والذاكرة بتنسحب من تحت إيده.
  if (!camLock(5000)) {
    g_log.println("[CAM] المستشعر مشغول — ما قدرنا نصوّر");
    snprintf(ev, sizeof(ev), "{\"id\":\"%s\",\"error\":\"camera_busy\"}", id.c_str());
    mqttPublishEvent(ev);
    return;
  }

  // الفلاش: بيشتعل قبل الالتقاط بلحظة عشان المستشعر يضبط تعريضه على الإضاءة
  bool useFlash = flashWantedForCapture(flash);
  if (useFlash) {
    g_log.printf("[CAM] flash on (level=%u)\n", g_flashLevel);
    flashSet(g_flashLevel, FLASH_WARMUP_MS + 800);
    delay(FLASH_WARMUP_MS);
  }

  // ارمي إطاراً قديماً من الـ buffer (مهم: أول fb_get بعد فترة بيرجع إطار قديم)
  camera_fb_t* stale = esp_camera_fb_get();
  if (stale) esp_camera_fb_return(stale);

  // التقاط الإطار الحديث
  camera_fb_t* fb = esp_camera_fb_get();

  // الفلاش بينطفي فوراً بعد الالتقاط — الباقي نشر بيوخد ثواني، ما إله داعي
  if (useFlash) flashOff();

  if (!fb) {
    // **محاولة إنعاش قبل الاستسلام.**
    //
    // المستشعر بيعلّق أحيانًا: بعد بثّ طويل، أو بعد ساعات بلا التقاط. والنتيجة
    // إنّ اللوح بيضلّ ينبض ويقول `cam=yes` — وهو مش قادر يصوّر. دورة كهربا
    // كاملة للمستشعر بترجّعه بأغلب الحالات. بنجرّبها مرّة؛ ولو ما زبطت بنقول
    // فشلنا بصراحة. والقفل معنا، فما حدا ماسك إطارًا وقت الـ`deinit`.
    g_log.println("[CAM] capture failed — بنعيد تشغيل المستشعر");
    esp_camera_deinit();
    delay(120);
    g_cameraReady = false;
    setupCamera();
    if (g_cameraReady) {
      settingsLoadFromNvs();   // الإعدادات بتضيع مع إعادة التشغيل
      camera_fb_t* s2 = esp_camera_fb_get();
      if (s2) esp_camera_fb_return(s2);
      fb = esp_camera_fb_get();
    }
  }

  if (!fb) {
    camUnlock();
    g_log.println("[CAM] capture failed");
    snprintf(ev, sizeof(ev), "{\"id\":\"%s\",\"error\":\"capture_failed\"}", id.c_str());
    mqttPublishEvent(ev);
    return;
  }

  // الطول قبل الإرجاع — بعد `fb_return` المخزن مش إلنا، والمشغّل ممكن يعبّيه
  // بإطار جديد وإحنا بنقرا منه.
  const size_t bytes = fb->len;
  g_log.printf("[CAM] captured %u bytes — uploading...\n", (unsigned)bytes);

  // **الرفع مباشرة للخادم، ومحاولة تانية بدل مسار احتياطي.**
  //
  // كان في احتياطي: لو الرفع فشل، الصورة بتتقطّع وتنبعت عبر الوسيط. وهاد المسار
  // كان بلا توقيع — أي حدا بيقدر ينشر ع موضوع الكاميرا كان بيقدر يزرع صورة
  // مكان صورة البيت — وصور البيت كانت بتمرق ع وسيط طرف تالت. وبنفس الوقت ما كان
  // بيوصّل إشي فعليًّا: القطع بتضيع بصمت. محاولة تانية بعد ثانية، وبعدها خطأ
  // صريح بيوصل التطبيق، أحسن من صورة بطيئة ومكشوفة ما بتوصل.
  bool ok = uploadSnapshot(id, fb->buf, bytes);
  if (!ok) {
    g_log.println("[CAM] upload failed — محاولة تانية بعد ثانية");
    camWait(1000);
    ok = uploadSnapshot(id, fb->buf, bytes);
  }
  esp_camera_fb_return(fb);
  camUnlock();

  if (ok) {
    snprintf(ev, sizeof(ev),
             "{\"id\":\"%s\",\"event\":\"uploaded\",\"bytes\":%u}",
             id.c_str(), (unsigned)bytes);
    mqttPublishEvent(ev);
    g_log.println("[CAM] upload ok");
    return;
  }
  snprintf(ev, sizeof(ev), "{\"id\":\"%s\",\"error\":\"upload_failed\"}", id.c_str());
  mqttPublishEvent(ev);
  g_log.println("[CAM] upload failed twice — reported");
}
