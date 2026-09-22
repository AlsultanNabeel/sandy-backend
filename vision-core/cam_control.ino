// =========================
// ESP32-CAM — Flash, sensor settings, command dispatch
// =========================
// كل قدرة بالعتاد مفتوحة كأمر عبر MQTT، وكل إعداد بينحفظ بالذاكرة الدائمة.
// الفكرة: ما نرجع نفلش الجهاز عشان نغيّر إعداد — الدماغ بالسحابة بيبعت أمر وخلص.
//
// الأوامر (topic: sandy/cam/command، صيغة JSON):
//   {"cmd":"flash","state":"on|off","level":0-255,"ms":1500}
//   {"cmd":"flash_mode","mode":"off|on|auto"}
//   {"cmd":"snapshot","id":"...","settle_ms":300,"flash":"auto"}
//   {"cmd":"burst","count":6,"interval_ms":800,"id":"...","flash":"off"}
//   {"cmd":"set","framesize":"VGA","quality":12,"brightness":1,...}
//   {"cmd":"get"}              → ينشر كل الإعدادات الحالية
//   {"cmd":"stream","state":"on|off"}
//   {"cmd":"save"} / {"cmd":"defaults"}
//   {"cmd":"reboot"}

#include <Preferences.h>

// ── إعلانات من ملفات تانية ──
void mqttPublishEvent(const char* json);
bool mqttPublishStatusJson(const char* json);
void startCamHttp();
void stopCamHttp();
bool camHttpRunning();

static Preferences g_prefs;

// حالة الفلاش الداخلية. المتغيّرات المشتركة بين الملفات معرّفة بالملف الرئيسي
// (Arduino بيلزق الملفات ورا بعض أبجدياً، فالمشترك لازم يكون قبل أول استعمال).
static bool          g_flashOn = false;
static unsigned long g_flashOffAtMs = 0;   // 0 = بلا مؤقت

// ─────────────────────────────────────────────────────────────
// JSON: قارئ صغير بدل مكتبة كاملة — الرسائل عندنا مسطّحة وبسيطة
// ─────────────────────────────────────────────────────────────
static int jsonValuePos(const String& src, const char* key) {
  String needle = "\"";
  needle += key;
  needle += "\"";
  int k = src.indexOf(needle);
  if (k < 0) return -1;
  int colon = src.indexOf(':', k + needle.length());
  if (colon < 0) return -1;
  int p = colon + 1;
  while (p < (int)src.length() && (src[p] == ' ' || src[p] == '\t')) p++;
  return p;
}

bool jsonHas(const String& src, const char* key) {
  return jsonValuePos(src, key) >= 0;
}

String jsonStr(const String& src, const char* key, const String& def) {
  int p = jsonValuePos(src, key);
  if (p < 0 || p >= (int)src.length()) return def;
  if (src[p] != '"') return def;
  int end = src.indexOf('"', p + 1);
  if (end < 0) return def;
  return src.substring(p + 1, end);
}

long jsonInt(const String& src, const char* key, long def) {
  int p = jsonValuePos(src, key);
  if (p < 0 || p >= (int)src.length()) return def;
  if (src[p] == '"') p++;                       // نقبل الرقم بين علامتين كمان
  bool neg = false;
  if (p < (int)src.length() && src[p] == '-') { neg = true; p++; }
  if (p >= (int)src.length() || !isdigit(src[p])) return def;
  long v = 0;
  int digits = 0;
  // تسع خانات بتكفّي كل قيمة عندنا؛ أكتر من هيك بيفيض `long` وبيطلع رقم غريب.
  while (p < (int)src.length() && isdigit(src[p])) {
    if (++digits > 9) return def;
    v = v * 10 + (src[p] - '0');
    p++;
  }
  return neg ? -v : v;
}

// معرّف طلب مقبول: حروف وأرقام وشرطة، لحدّ أربعين. المعرّف بيروح بترويسة طلب
// الرفع وبـ JSON الأحداث؛ علامة تنصيص أو سطر جديد فيه كانت بتكسر الاتنين —
// وبتسمح بحقن ترويسة بطلب الرفع.
bool camValidId(const String& id) {
  if (id.length() == 0 || id.length() > 40) return false;
  for (size_t i = 0; i < id.length(); i++) {
    char c = id[i];
    if (!(isalnum((unsigned char)c) || c == '-' || c == '_')) return false;
  }
  return true;
}

// هروب لقيمة نصّية جوّا JSON.
static String jsonEscape(const String& in) {
  String out;
  out.reserve(in.length() + 4);
  for (size_t i = 0; i < in.length(); i++) {
    char c = in[i];
    if (c == '"' || c == '\\') { out += '\\'; out += c; }
    else if ((unsigned char)c < 0x20) out += ' ';
    else out += c;
  }
  return out;
}

// **حدّ واحد لكل إشي بيشغّل المستشعر أو الفلاش.** كان في حدّ ع مسار قديم ما
// حدا بيستعمله، والمسار اللي بيستعمله الخادم (التصوير والسلسلة والبث) كان بلا
// حدّ — يعني تكرار الطلب مع «فلاش شغّال» بيسخّن اللمبة وبيوقّع الكهربا.
static unsigned long g_lastHeavyCmdMs = 0;
static bool g_heavyCmdSeen = false;
bool camCommandAllowed() {
  unsigned long now = millis();
  if (g_heavyCmdSeen && now - g_lastHeavyCmdMs < CAM_COMMAND_MIN_GAP_MS) return false;
  g_heavyCmdSeen = true;
  g_lastHeavyCmdMs = now;
  return true;
}

// ─────────────────────────────────────────────────────────────
// الفلاش
// ─────────────────────────────────────────────────────────────
void flashInit() {
  ledcAttachChannel(FLASH_LED_GPIO, FLASH_PWM_FREQ_HZ, FLASH_PWM_BITS, FLASH_PWM_CHANNEL);
  ledcWrite(FLASH_LED_GPIO, 0);
  g_flashOn = false;
}

void flashSet(uint8_t level, unsigned long autoOffMs) {
  ledcWrite(FLASH_LED_GPIO, level);
  g_flashOn = level > 0;
  if (level > 0) {
    // حتى لو ما طُلب مؤقت، منحط سقف أمان — اللمبة بتسخن وبتاكل تيار
    unsigned long limit = autoOffMs > 0 ? min(autoOffMs, (unsigned long)FLASH_MAX_ON_MS)
                                        : (unsigned long)FLASH_MAX_ON_MS;
    g_flashOffAtMs = millis() + limit;
  } else {
    g_flashOffAtMs = 0;
  }
}

void flashOff() { flashSet(0, 0); }

bool flashIsOn() { return g_flashOn; }

// تُنادى من الـ loop — تطفي الفلاش لما يخلص وقته
void flashTick() {
  // بالفرق مش بالقيمة، عشان لفّة العدّاد بعد تسعة وأربعين يوم.
  if (g_flashOn && g_flashOffAtMs && (long)(millis() - g_flashOffAtMs) >= 0) {
    g_log.println("[FLASH] auto-off (safety timer)");
    flashOff();
  }
}

// عتمة؟ منقرأها من كسب المستشعر: كل ما زاد الكسب، كل ما كانت الإضاءة أقل.
//
// **الكسب الحيّ، مش الإعداد.** `status.agc_gain` هو الكسب اليدوي اللي بينحطّ
// لمّا الكسب التلقائي مطفي — وهو مشغّل عندنا، فالقيمة ضايلة صفر ووضع «تلقائي»
// ما كان يشعل الفلاش ولا مرّة، وصور الليل طالعة سودا. مستشعر OV2640 بيحكي
// كسبه الحالي بسجلّ `GAIN` (بنك المستشعر، العنوان صفر)؛ غير هيك بنرجع للإعداد.
bool sceneIsDark() {
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return false;
  if (s->id.PID == OV2640_PID && s->status.agc && s->get_reg) {
    int g = s->get_reg(s, 0x100 | 0x00, 0xff);
    // البتات العليا مضاعفات (×٢ لكل بت)، والسفلى كسر. من ×٤ وطالع = عتمة.
    if (g >= 0) return g >= FLASH_AUTO_GAIN_REG_THRESHOLD;
  }
  return s->status.agc_gain >= FLASH_AUTO_GAIN_THRESHOLD;
}

// هل نشعل الفلاش لهاللقطة؟
extern bool g_flashLockedByBrownout;

bool flashWantedForCapture(FlashMode mode) {
  // بعد انهيار كهربا ما في فلاش للّقطات، مهما قال الوضع المحفوظ أو الطلب.
  if (g_flashLockedByBrownout) return false;
  switch (mode) {
    case FLASH_MODE_ON:   return true;
    case FLASH_MODE_OFF:  return false;
    case FLASH_MODE_AUTO: return sceneIsDark();
  }
  return false;
}

static FlashMode parseFlashMode(const String& v, FlashMode def) {
  if (v == "on"   || v == "1") return FLASH_MODE_ON;
  if (v == "off"  || v == "0") return FLASH_MODE_OFF;
  if (v == "auto")             return FLASH_MODE_AUTO;
  return def;
}

static const char* flashModeName(FlashMode m) {
  switch (m) {
    case FLASH_MODE_ON:  return "on";
    case FLASH_MODE_OFF: return "off";
    default:             return "auto";
  }
}

// ─────────────────────────────────────────────────────────────
// أحجام الصورة
// ─────────────────────────────────────────────────────────────
struct FrameSizeName { const char* name; framesize_t size; };
static const FrameSizeName kFrameSizes[] = {
  {"96X96",   FRAMESIZE_96X96},   {"QQVGA", FRAMESIZE_QQVGA},
  {"QCIF",    FRAMESIZE_QCIF},    {"HQVGA", FRAMESIZE_HQVGA},
  {"240X240", FRAMESIZE_240X240}, {"QVGA",  FRAMESIZE_QVGA},
  {"CIF",     FRAMESIZE_CIF},     {"HVGA",  FRAMESIZE_HVGA},
  {"VGA",     FRAMESIZE_VGA},     {"SVGA",  FRAMESIZE_SVGA},
  {"XGA",     FRAMESIZE_XGA},     {"HD",    FRAMESIZE_HD},
  {"SXGA",    FRAMESIZE_SXGA},    {"UXGA",  FRAMESIZE_UXGA},
};
static const size_t kFrameSizeCount = sizeof(kFrameSizes) / sizeof(kFrameSizes[0]);

static bool frameSizeFromName(const String& name, framesize_t* out) {
  String up = name;
  up.toUpperCase();
  for (size_t i = 0; i < kFrameSizeCount; i++) {
    if (up == kFrameSizes[i].name) { *out = kFrameSizes[i].size; return true; }
  }
  return false;
}

static const char* frameSizeName(framesize_t size) {
  for (size_t i = 0; i < kFrameSizeCount; i++) {
    if (kFrameSizes[i].size == size) return kFrameSizes[i].name;
  }
  return "?";
}

// ─────────────────────────────────────────────────────────────
// إعدادات المستشعر — كلها قابلة للتغيير وقت التشغيل
// ─────────────────────────────────────────────────────────────
// اسم الأمر ← دالة الضبط ← الحد الأدنى/الأعلى. أي إشي بيقدر يعمله المستشعر
// موجود هون، حتى لو ما بنستعمله هلأ — عشان ما نرجع نفلش لما نحتاجه.
struct SensorSetting {
  const char* key;
  int (*apply)(sensor_t*, int);
  int lo;
  int hi;
};

static int setFramesizeInt(sensor_t* s, int v) { return s->set_framesize(s, (framesize_t)v); }
static int setGainceilInt(sensor_t* s, int v)  { return s->set_gainceiling(s, (gainceiling_t)v); }

static const SensorSetting kSettings[] = {
  {"quality",        [](sensor_t* s, int v) { return s->set_quality(s, v); },        4,  63},
  {"brightness",     [](sensor_t* s, int v) { return s->set_brightness(s, v); },    -2,   2},
  {"contrast",       [](sensor_t* s, int v) { return s->set_contrast(s, v); },      -2,   2},
  {"saturation",     [](sensor_t* s, int v) { return s->set_saturation(s, v); },    -2,   2},
  {"sharpness",      [](sensor_t* s, int v) { return s->set_sharpness(s, v); },     -3,   3},
  {"denoise",        [](sensor_t* s, int v) { return s->set_denoise(s, v); },        0,   8},
  {"special_effect", [](sensor_t* s, int v) { return s->set_special_effect(s, v); }, 0,   6},
  {"wb_mode",        [](sensor_t* s, int v) { return s->set_wb_mode(s, v); },        0,   4},
  {"awb",            [](sensor_t* s, int v) { return s->set_whitebal(s, v); },       0,   1},
  {"awb_gain",       [](sensor_t* s, int v) { return s->set_awb_gain(s, v); },       0,   1},
  {"aec",            [](sensor_t* s, int v) { return s->set_exposure_ctrl(s, v); },  0,   1},
  {"aec2",           [](sensor_t* s, int v) { return s->set_aec2(s, v); },           0,   1},
  {"ae_level",       [](sensor_t* s, int v) { return s->set_ae_level(s, v); },      -2,   2},
  {"aec_value",      [](sensor_t* s, int v) { return s->set_aec_value(s, v); },      0, 1200},
  {"agc",            [](sensor_t* s, int v) { return s->set_gain_ctrl(s, v); },      0,   1},
  {"agc_gain",       [](sensor_t* s, int v) { return s->set_agc_gain(s, v); },       0,  30},
  {"gainceiling",    setGainceilInt,                                                 0,   6},
  {"bpc",            [](sensor_t* s, int v) { return s->set_bpc(s, v); },            0,   1},
  {"wpc",            [](sensor_t* s, int v) { return s->set_wpc(s, v); },            0,   1},
  {"raw_gma",        [](sensor_t* s, int v) { return s->set_raw_gma(s, v); },        0,   1},
  {"lenc",           [](sensor_t* s, int v) { return s->set_lenc(s, v); },           0,   1},
  {"hmirror",        [](sensor_t* s, int v) { return s->set_hmirror(s, v); },        0,   1},
  {"vflip",          [](sensor_t* s, int v) { return s->set_vflip(s, v); },          0,   1},
  {"dcw",            [](sensor_t* s, int v) { return s->set_dcw(s, v); },            0,   1},
  {"colorbar",       [](sensor_t* s, int v) { return s->set_colorbar(s, v); },       0,   1},
  {"framesize",      setFramesizeInt,                                                0,  (int)CAMERA_MAX_FRAME_SIZE},
};
static const size_t kSettingCount = sizeof(kSettings) / sizeof(kSettings[0]);

static int readSetting(sensor_t* s, const char* key) {
  if (!strcmp(key, "quality"))        return s->status.quality;
  if (!strcmp(key, "brightness"))     return s->status.brightness;
  if (!strcmp(key, "contrast"))       return s->status.contrast;
  if (!strcmp(key, "saturation"))     return s->status.saturation;
  if (!strcmp(key, "sharpness"))      return s->status.sharpness;
  if (!strcmp(key, "denoise"))        return s->status.denoise;
  if (!strcmp(key, "special_effect")) return s->status.special_effect;
  if (!strcmp(key, "wb_mode"))        return s->status.wb_mode;
  if (!strcmp(key, "awb"))            return s->status.awb;
  if (!strcmp(key, "awb_gain"))       return s->status.awb_gain;
  if (!strcmp(key, "aec"))            return s->status.aec;
  if (!strcmp(key, "aec2"))           return s->status.aec2;
  if (!strcmp(key, "ae_level"))       return s->status.ae_level;
  if (!strcmp(key, "aec_value"))      return s->status.aec_value;
  if (!strcmp(key, "agc"))            return s->status.agc;
  if (!strcmp(key, "agc_gain"))       return s->status.agc_gain;
  if (!strcmp(key, "gainceiling"))    return s->status.gainceiling;
  if (!strcmp(key, "bpc"))            return s->status.bpc;
  if (!strcmp(key, "wpc"))            return s->status.wpc;
  if (!strcmp(key, "raw_gma"))        return s->status.raw_gma;
  if (!strcmp(key, "lenc"))           return s->status.lenc;
  if (!strcmp(key, "hmirror"))        return s->status.hmirror;
  if (!strcmp(key, "vflip"))          return s->status.vflip;
  if (!strcmp(key, "dcw"))            return s->status.dcw;
  if (!strcmp(key, "colorbar"))       return s->status.colorbar;
  if (!strcmp(key, "framesize"))      return s->status.framesize;
  return 0;
}

static int clampInt(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

// بيرجّع عدد الإعدادات اللي انطبقت فعلاً
static int applySettingsFromJson(const String& payload, bool persist) {
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return 0;

  int applied = 0;
  for (size_t i = 0; i < kSettingCount; i++) {
    const SensorSetting& def = kSettings[i];
    if (!jsonHas(payload, def.key)) continue;

    int v;
    if (!strcmp(def.key, "framesize")) {
      // منقبل الاسم ("VGA") أو الرقم — الاسم أوضح للسحابة
      String nameVal = jsonStr(payload, def.key, "");
      framesize_t fs;
      if (nameVal.length() && frameSizeFromName(nameVal, &fs)) {
        v = (int)fs;
      } else {
        v = (int)jsonInt(payload, def.key, s->status.framesize);
      }
    } else {
      v = (int)jsonInt(payload, def.key, readSetting(s, def.key));
    }

    v = clampInt(v, def.lo, def.hi);
    if (def.apply(s, v) == 0) {
      applied++;
      if (persist) g_prefs.putInt(def.key, v);
    } else {
      g_log.printf("[SET] %s=%d rejected by sensor\n", def.key, v);
    }
  }
  return applied;
}

void settingsLoadFromNvs() {
  sensor_t* s = esp_camera_sensor_get();
  if (!s) return;
  int restored = 0;
  for (size_t i = 0; i < kSettingCount; i++) {
    const SensorSetting& def = kSettings[i];
    if (!g_prefs.isKey(def.key)) continue;
    int v = clampInt(g_prefs.getInt(def.key, readSetting(s, def.key)), def.lo, def.hi);
    if (def.apply(s, v) == 0) restored++;
  }
  int storedMode = g_prefs.getInt("flash_mode", (int)FLASH_MODE_AUTO);
  g_flashMode  = (storedMode >= FLASH_MODE_OFF && storedMode <= FLASH_MODE_AUTO)
                     ? (FlashMode)storedMode : FLASH_MODE_AUTO;
  g_flashLevel = (uint8_t)clampInt(g_prefs.getInt("flash_level", FLASH_DEFAULT_LEVEL), 0, 255);
  g_log.printf("[SET] restored %d settings from NVS (flash=%s level=%u)\n",
               restored, flashModeName(g_flashMode), g_flashLevel);
}

void settingsInit() {
  g_prefs.begin(SETTINGS_NVS_NAMESPACE, false);
}

static void settingsClear() {
  g_prefs.clear();
  g_log.println("[SET] stored settings cleared — defaults on next boot");
}

// ─────────────────────────────────────────────────────────────
// نشر الحالة الكاملة (كل الإعدادات + حالة الجهاز)
// ─────────────────────────────────────────────────────────────
void publishFullStatus() {
  sensor_t* s = esp_camera_sensor_get();
  String out = "{";
  out += "\"uptime_s\":" + String(millis() / 1000);
  out += ",\"rssi\":" + String(WiFi.RSSI());
  out += ",\"ip\":\"" + WiFi.localIP().toString() + "\"";
  out += ",\"heap\":" + String(ESP.getFreeHeap());
  out += ",\"psram\":" + String(ESP.getFreePsram());
  out += ",\"camera_ready\":" + String(g_cameraReady ? "true" : "false");
  out += ",\"flash_mode\":\"" + String(flashModeName(g_flashMode)) + "\"";
  out += ",\"flash_level\":" + String(g_flashLevel);
  out += ",\"flash_on\":" + String(flashIsOn() ? "true" : "false");
  out += ",\"stream\":" + String(camHttpRunning() ? "true" : "false");
  out += ",\"stream_url\":\"http://" + WiFi.localIP().toString() + "/stream\"";
  if (s) {
    out += ",\"framesize\":\"" + String(frameSizeName((framesize_t)s->status.framesize)) + "\"";
    for (size_t i = 0; i < kSettingCount; i++) {
      const char* key = kSettings[i].key;
      if (!strcmp(key, "framesize")) continue;   // نُشر بالاسم فوق
      out += ",\"" + String(key) + "\":" + String(readSetting(s, key));
    }
  }
  out += "}";
  mqttPublishStatusJson(out.c_str());
}

static void publishAck(const char* cmd, bool ok, const String& detail) {
  String out = "{\"cmd\":\"" + jsonEscape(String(cmd)) + "\",\"ok\":" + (ok ? "true" : "false");
  if (detail.length()) out += ",\"detail\":\"" + jsonEscape(detail) + "\"";
  out += "}";
  mqttPublishEvent(out.c_str());
}

// ─────────────────────────────────────────────────────────────
// تنفيذ الأوامر
// ─────────────────────────────────────────────────────────────
void handleCamCommand(const String& payload) {
  String cmd = jsonStr(payload, "cmd", "");
  if (cmd.length() == 0) {
    publishAck("?", false, "missing cmd");
    return;
  }
  g_log.printf("[CMD] %s\n", cmd.c_str());

  if (cmd == "flash") {
    String state = jsonStr(payload, "state", "on");
    long level = jsonInt(payload, "level", g_flashLevel);
    long ms    = jsonInt(payload, "ms", 0);
    if (state == "off" || level <= 0) {
      flashOff();
      publishAck("flash", true, "off");
    } else {
      g_flashLevel = (uint8_t)clampInt(level, 1, 255);
      flashSet(g_flashLevel, (unsigned long)ms);
      g_prefs.putInt("flash_level", g_flashLevel);
      publishAck("flash", true, "on level=" + String(g_flashLevel));
    }
    return;
  }

  if (cmd == "flash_level") {
    // الشدّة للّقطات الجاية، بلا تشغيل. صفر ما إله معنى كشدّة — الإطفاء إله
    // وضع «مطفي».
    g_flashLevel = (uint8_t)clampInt(jsonInt(payload, "level", g_flashLevel), 1, 255);
    g_prefs.putInt("flash_level", g_flashLevel);
    // لو شغّال هلّق، بيتغيّر لحظيًّا — المنزلق بيعطي ردّة فعل وإنت عم تحرّكه.
    if (flashIsOn()) ledcWrite(FLASH_LED_GPIO, g_flashLevel);
    publishAck("flash_level", true, String(g_flashLevel));
    return;
  }

  if (cmd == "flash_mode") {
    g_flashMode = parseFlashMode(jsonStr(payload, "mode", "auto"), g_flashMode);
    g_prefs.putInt("flash_mode", (int)g_flashMode);
    publishAck("flash_mode", true, flashModeName(g_flashMode));
    return;
  }

  if (cmd == "snapshot") {
    String id = jsonStr(payload, "id", String("s") + String(millis()));
    if (!camValidId(id)) { publishAck("snapshot", false, "bad id"); return; }
    if (g_snapshotPending) { publishAck("snapshot", false, "busy"); return; }
    if (!camCommandAllowed()) { publishAck("snapshot", false, "too soon"); return; }
    g_snapshotSettleMs = (unsigned int)clampInt(jsonInt(payload, "settle_ms", 0), 0, CAPTURE_MAX_SETTLE_MS);
    g_snapshotFlash = parseFlashMode(jsonStr(payload, "flash", ""), g_flashMode);
    g_currentRequestId = id;
    g_snapshotPending = true;
    publishAck("snapshot", true, id);
    return;
  }

  if (cmd == "burst") {
    String burstId = jsonStr(payload, "id", String("b") + String(millis()));
    if (!camValidId(burstId) || burstId.length() > 34) {   // مكان للاحقة «-٢٣»
      publishAck("burst", false, "bad id");
      return;
    }
    if (g_burstRemaining > 0) { publishAck("burst", false, "busy"); return; }
    if (!camCommandAllowed()) { publishAck("burst", false, "too soon"); return; }
    long count = clampInt(jsonInt(payload, "count", 3), 1, BURST_MAX_FRAMES);
    long gap   = jsonInt(payload, "interval_ms", 800);
    if (gap < BURST_MIN_INTERVAL_MS) gap = BURST_MIN_INTERVAL_MS;
    g_burstBaseId      = burstId;
    g_burstIntervalMs  = (unsigned long)gap;
    g_burstRemaining   = (unsigned int)count;
    g_burstIndex       = 0;
    g_burstNextAtMs    = millis();
    g_snapshotSettleMs = (unsigned int)clampInt(jsonInt(payload, "settle_ms", 0), 0, CAPTURE_MAX_SETTLE_MS);
    g_snapshotFlash    = parseFlashMode(jsonStr(payload, "flash", ""), g_flashMode);
    publishAck("burst", true, String(count) + " frames every " + String(gap) + "ms");
    return;
  }

  if (cmd == "set") {
    bool persist = jsonInt(payload, "save", 1) != 0;
    int applied = applySettingsFromJson(payload, persist);
    publishAck("set", applied > 0, String(applied) + " applied");
    publishFullStatus();
    return;
  }

  if (cmd == "get") {
    publishFullStatus();
    return;
  }

  if (cmd == "stream") {
    // **الاتنين مع بعض، والمشاهد بيختار.**
    //
    // المحلي سريع وسلس وبس ببيتك. والبعيد أبطأ وبيشتغل من أي مكان. تشغيلهن
    // سوا معناه إنّ التطبيق ما بيحتاج يعرف إنت وين — بيجرّب المحلي، وإذا ما
    // وصل بيسحب من الخادم.
    //
    // والكلفة بسيطة: المحلي ما بيصوّر إلا لمّا حدا يتفرّج، والبعيد بيرفع إطارًا
    // كل تلت ثانية. اللوح بيحمل التنين.
    String state = jsonStr(payload, "state", "on");
    if (state == "off") {
      stopCamHttp();
      camRemoteStream(false);
      publishAck("stream", true, "off");
    } else {
      if (!camCommandAllowed()) { publishAck("stream", false, "too soon"); return; }
      startCamHttp();
      camRemoteStream(true);
      publishAck("stream", camHttpRunning(),
                 "http://" + WiFi.localIP().toString() + "/stream");
    }
    return;
  }

  if (cmd == "save") {
    applySettingsFromJson(payload, true);
    publishAck("save", true, "stored");
    return;
  }

  if (cmd == "defaults") {
    settingsClear();
    publishAck("defaults", true, "rebooting");
    delay(200);
    ESP.restart();
    return;
  }

  if (cmd == "reboot") {
    publishAck("reboot", true, "");
    delay(200);
    ESP.restart();
    return;
  }

  publishAck(cmd.c_str(), false, "unknown cmd");
}
