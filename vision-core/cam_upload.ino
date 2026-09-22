// =========================
// رفع الصورة للخادم مباشرة — طلب واحد بدل عشرين رسالة
// =========================
//
// ليش هالملف موجود، بجملة: **الوسيط بروتوكول أوامر، مش ناقل ملفات.**
//
// الصورة كانت بتتقسّم وتتشفّر بترميز بيكبّرها تلتًا، وتتبعت قطعة قطعة بجودة
// نشر ما إلها إقرار — يعني القطعة إمّا توصل أو تضيع **بصمت**. وعشان نلتفّ ع
// هاد، انبنت طبقة كاملة عند الخادم: تجميع، وترقيم، وصندوق وارد، وتذاكر،
// ومهلات، وإعادة محاولة. كلها موجودة لتصليح مشكلة ما كان لازم تصير.
//
// والقياس اللي حسم: نبضة الكاميرا (خمس مئة بايت) بتوصل دايمًا، وقطعة الصورة
// (ألف وأربعمية) ما بتوصل ولا مرّة — نفس اللوح، نفس الثانية، نفس الاتصال.
//
// هون الصورة بتنبعت زي ما هي: بايتاتها الأصلية بجسم طلب واحد. البروتوكول
// بيتكفّل بالتقطيع والترتيب وإعادة الإرسال — وهاي شغلته من خمسين سنة.
//
// والتوثيق نفس فكرة مقبس الصوت: توقيع بمفتاح مشترك ع (الوحدة + الطلب + الوقت).
// ما في حساب ولا جلسة، والوقت بيمنع إعادة إرسال طلب قديم انلقط.

#include <WiFiClientSecure.h>
#include "mbedtls/md.h"
#include <Preferences.h>
#include <time.h>

String camNodeId();
extern volatile bool g_streamViewerActive;
bool camLock(uint32_t waitMs);
void camUnlock();
void camWait(unsigned long ms);
void camWdtFeed();

// عنوان الخادم ومفتاح الرفع المشترك: قيمهم الافتراضية بـ config.h.

// مزامنة الساعة — **شرط للرفع، مش رفاهية.**
//
// اللوح بيقلع وساعته سنة سبعين. والتوقيع بيحمل الوقت عشان يمنع إعادة إرسال
// طلب قديم انلقط، فالخادم بيرفض أي طلب أقدم من دقيقتين — وطلب من سنة سبعين
// عمره خمسة وخمسين سنة.
//
// وهاد بالضبط اللي صار: الرفع وصل الخادم ورجع `400`. مش عطل شبكة ولا حجم ولا
// مفتاح — ساعة.
//
// بتنادى مرّة، وبتستنّى بحد أقصى عشر ثواني. لو ما زبطت، الرفع بيفشل بوضوح
// وبترجع الصورة للمسار القديم بدل ما تضيع.
static bool g_clockReady = false;
// أي ساعة قبل هاد التاريخ (تشرين التاني ٢٠٢٣) معناها إنها لسا ما انضبطت.
#define CAM_CLOCK_SANE_EPOCH 1700000000

void camSyncClock() {
  if (g_clockReady) return;
  // الراوتر أول: كتير شبكات بتحجب خدمة الوقت العامة، والراوتر نفسه غالبًا
  // بيجاوب. بعدين الخدمات العامة.
  static char gw[16];
  strncpy(gw, WiFi.gatewayIP().toString().c_str(), sizeof(gw) - 1);
  configTime(0, 0, "pool.ntp.org", "time.google.com", gw);
  unsigned long t0 = millis();
  while (millis() - t0 < 10000) {
    if (time(nullptr) > CAM_CLOCK_SANE_EPOCH) {   // أي وقت معقول بعد ٢٠٢٣
      g_clockReady = true;
      g_log.println("[TIME] الساعة انضبطت");
      return;
    }
    camWait(200);
  }
  g_log.println("[TIME] ⚠️ الساعة ما انضبطت — الرفع رح ينرفض");
}

bool camClockReady() { return g_clockReady; }

// مفتاح الكاميرا الخاص.
//
// المفتاح المشترك محروق بكل لوح، فقراءته من كاميرا وحدة كانت بتكفّي ترفع صور
// باسم أي كاميرا تانية. بالدقايق اللي بعد ما المالك يقرن الروبوت بالتطبيق،
// ردّ الخادم ع رفع موقّع بالمشترك بيحمل مفتاح خاص بهالكاميرا — بنخزّنه هون
// وبنوقّع فيه كل رفع بعده. أوّل رفع ناجح فيه بيخلّي الخادم يرفض المشترك لهاد
// اللوح. ولو الخادم قال «key_unknown» (انفكّ الاقتران) بنمسحه وبنرجع للمشترك.
static uint8_t g_ownKey[32];
static bool    g_hasOwnKey = false;
static bool    g_ownKeyLoaded = false;

static int hexNibble(char c) {
  if (c >= '0' && c <= '9') return c - '0';
  if (c >= 'a' && c <= 'f') return c - 'a' + 10;
  if (c >= 'A' && c <= 'F') return c - 'A' + 10;
  return -1;
}

static bool parseKeyHex(const String& hex, uint8_t out[32]) {
  if (hex.length() != 64) return false;
  for (int i = 0; i < 32; i++) {
    int hi = hexNibble(hex[2 * i]), lo = hexNibble(hex[2 * i + 1]);
    if (hi < 0 || lo < 0) return false;
    out[i] = (uint8_t)((hi << 4) | lo);
  }
  return true;
}

static void ownKeyLoad() {
  if (g_ownKeyLoaded) return;
  g_ownKeyLoaded = true;
  Preferences p;
  if (!p.begin("sandy_ckey", true)) return;
  String hex = p.getString("k", "");
  p.end();
  g_hasOwnKey = parseKeyHex(hex, g_ownKey);
  if (g_hasOwnKey) g_log.println("[UP] مفتاح الكاميرا الخاص جاهز");
}

static void ownKeyStore(const String& hex) {
  uint8_t k[32];
  if (!parseKeyHex(hex, k)) return;
  Preferences p;
  if (!p.begin("sandy_ckey", false)) return;
  bool ok = p.putString("k", hex) == hex.length();
  p.end();
  if (!ok) return;
  memcpy(g_ownKey, k, sizeof(k));
  g_hasOwnKey = true;
  g_log.println("[UP] استلمنا مفتاح الكاميرا الخاص");
}

static void ownKeyDrop() {
  Preferences p;
  if (p.begin("sandy_ckey", false)) { p.remove("k"); p.end(); }
  memset(g_ownKey, 0, sizeof(g_ownKey));
  g_hasOwnKey = false;
  g_log.println("[UP] الخادم ما بيعرف مفتاحنا — رجعنا للمشترك لحد الاقتران الجاي");
}

static String hmacHex(const String& msg) {
  const unsigned char* key = g_hasOwnKey ? g_ownKey : (const unsigned char*)g_id.sharedKey.c_str();
  size_t keyLen = g_hasOwnKey ? sizeof(g_ownKey) : g_id.sharedKey.length();
  uint8_t out[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, key, keyLen);
  mbedtls_md_hmac_update(&ctx, (const unsigned char*)msg.c_str(), msg.length());
  mbedtls_md_hmac_finish(&ctx, out);
  mbedtls_md_free(&ctx);

  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + i * 2, "%02x", out[i]);
  hex[64] = '\0';
  return String(hex);
}

// بصمة الصورة نفسها — بتدخل بالتوقيع، فالصورة ما بتنبدّل ع الطريق بنفس
// التوقيع.
static String sha256Hex(const uint8_t* data, size_t len) {
  uint8_t out[32];
  mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), data, len, out);
  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + i * 2, "%02x", out[i]);
  hex[64] = '\0';
  return String(hex);
}

// ── البثّ البعيد ──────────────────────────────────────────────────────────
//
// البثّ المحلي بيروح من الكاميرا لتلفونك مباشرة: سريع وسلس، **وبس ببيتك**.
// الراوتر بيعطي الكاميرا عنوانًا داخليًّا ما بيدلّ ع إشي من برّا.
//
// وهون الإطار بيمشي بنفس مسار الصورة اللي اشتغل: بيترفع للخادم، والتطبيق
// بيسحبه. أبطأ، **بس بيشتغل من أي مكان بالدنيا** — ومن نفس الشيفرة، بلا منفذ
// مفتوح بالراوتر ولا خدمة وسيطة.
//
// إطار كل تلت ثانية تقريبًا: ثلاثة بالثانية. مش فيديو سينمائي، وهي نفس وتيرة
// «العرض البعيد» بكاميرات المراقبة اللي بتشتغل ع بيانات الجوّال — لأنّ الحدّ
// هو الشبكة واللوح، مش الاختيار.
static bool g_remoteStream = false;
static unsigned long g_remoteNextMs = 0;
static unsigned long g_remoteUntilMs = 0;

void camRemoteStream(bool on) {
  g_remoteStream = on;
  g_remoteNextMs = 0;
  // **مهلة انتهاء — البثّ ما بيجوز يشتغل للأبد.**
  //
  // البثّ المحلي عنده مهلة من زمان، وأنا ضفت البعيد بلاها. فلو المستخدم سكّر
  // التطبيق بلا ما يوقّفه، اللوح بيضلّ يصوّر ويرفع **للأبد**: بيسخن، وبياكل
  // بيانات، وبيحجز الحلقة — فما بيقدر يستقبل ترقية ولا يردّ بسرعة ع أمر.
  //
  // وهاد اللي منع الترقية ع الشبكة: اللوح مشغول برفع إطار كل تلت ثانية، وكل
  // رفعة بتاخد حوالي ثانية، فما بيلحق يردّ ع طلب الترقية أصلًا.
  //
  // خمس دقايق بتكفّي جلسة مشاهدة، وبتنتهي لحالها لو حدا نسي.
  g_remoteUntilMs = on ? millis() + CAM_REMOTE_STREAM_MAX_MS : 0;
  g_log.printf("[UP] البثّ البعيد %s\n", on ? "اشتغل" : "وقف");
}

bool camRemoteStreaming() { return g_remoteStream; }

// بتنادى من الحلقة الرئيسية. بتلتقط وترفع إطارًا واحدًا لمّا يحين وقته.
void camRemoteStreamTick() {
  if (!g_remoteStream || !g_cameraReady) return;

  if (g_remoteUntilMs && (long)(millis() - g_remoteUntilMs) > 0) {
    g_log.println("[UP] البثّ البعيد وقف لحاله — انتهت المهلة");
    camRemoteStream(false);
    return;
  }

  // **مخزن إطار واحد — يعني مستهلك واحد بس.**
  //
  // شغّلت البثّين سوا وقلت «اللوح بيحمل التنين». ما بيحمل: المستشعر عنده مخزن
  // إطار واحد، والبثّ المحلي بياخده بحلقة متواصلة. فأول ما هالدالة تطلب إطارًا
  // بنفس اللحظة، واحد منهن بياخد فراغ — والمحلي بيقطع، والالتقاط اللي بعده
  // بيفشل.
  //
  // وهاد بالضبط اللي صار: «شاشة سودا» ثم `capture failed`. عطلان مختلفان
  // ظاهريًّا، وسببهن واحد.
  //
  // فلمّا يكون في متفرّج محلي، هو الأولى: هو الأسرع والأوضح، والبعيد ما إله
  // لزوم وإنت واقف بنفس الغرفة.
  if (g_streamViewerActive) return;

  if (g_remoteNextMs && (long)(millis() - g_remoteNextMs) < 0) return;
  g_remoteNextMs = millis() + CAM_REMOTE_STREAM_INTERVAL_MS;

  if (!camLock(200)) return;   // المستشعر مشغول بلقطة — الإطار الجاي
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    camUnlock();
    // إطار فاضي بعد بثّ محلي: المستشعر لسا بيسلّم مخزنه. نجرّب بالدورة الجاية
    // بدل ما نلحّ عليه ونخلّيه أسوأ.
    g_log.println("[UP] المستشعر مش جاهز — بنأجّل الإطار");
    return;
  }
  // معرّف ثابت: الإطار الجديد بيستبدل القديم بصندوق الخادم بدل ما يتراكم.
  // بثّ بيخزّن كل إطار بيملا القرص بدقايق، والمشاهد بده الأحدث وبس.
  bool ok = uploadSnapshot("live", fb->buf, fb->len);
  esp_camera_fb_return(fb);
  camUnlock();
  if (!ok) {
    // فشل إطار واحد ما بيوقّف البثّ — الشبكة بتتعثّر، والمشاهد بيشوف تهنيقة
    // بدل ما ينقطع كل إشي. بس لو تعثّرت كتير، بتبان بالسجل.
    g_log.println("[UP] إطار ضاع");
  }
}

// **اتصال واحد بيضلّ مفتوح، مش اتصال لكل صورة.**
//
// كل رفعة كانت بتفتح اتصالًا مشفّرًا جديدًا: مصافحة بتاخد حوالي ثانية
// وأربعين كيلوبايت من الذاكرة الداخلية، وبعدين بتنسكّر. بالبث البعيد هاد تلات
// مرّات بالثانية لخمس دقايق، وجنبه اتصال الوسيط المشفّر ماسك حصّته. الذاكرة
// بتتقطّع مع الوقت لحدّ «فشل تخصيص ذاكرة» — والرفع بيوقف، والبث بيوقف،
// والصورة ما بتوصل. اتصال مفتوح بيدفع المصافحة مرّة، وبيخلّي الذاكرة ثابتة.
static WiFiClientSecure g_upClient;
static bool g_upClientReady = false;

// قبل التحديث: الاتصال المفتوح ماسك ذاكرة تشفير كاملة، والتنزيل بدّه وحدة تانية.
void camUploadClose() {
  g_upClient.stop();
}

static bool upEnsureConnected() {
  if (g_upClient.connected()) return true;
  g_upClient.stop();
  if (!g_upClientReady) {
    // بنتحقّق من شهادة الخادم بقائمة جذور قصيرة (sandy_ca_roots.h) — المخزن
    // الكامل ما بيسع، بس خمس جذور بيسعوا. بلا تحقّق، أي حدا ع نفس الشبكة
    // بياخد صور البيت ومفتاح الكاميرا.
    g_upClient.setCACert(SANDY_CA_ROOTS);
    g_upClient.setTimeout(15000);       // ميلي ثانية (اتصال وكتابة)
    g_upClient.setHandshakeTimeout(15); // ثواني — الافتراضي دقيقتين، أطول من الحارس
    g_upClientReady = true;
  }
  camWdtFeed();
  if (!g_upClient.connect(SANDY_UPLOAD_HOST, 443)) {
    char err[96] = {0};
    g_upClient.lastError(err, sizeof(err));
    g_log.printf("[UP] فشل الاتصال بالخادم (%s) free=%u largest=%u\n",
                 err[0] ? err : "?", (unsigned)ESP.getFreeHeap(),
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_8BIT));
    g_upClient.stop();
    return false;
  }
  return true;
}

// سطر من الردّ بمهلة. بيرجّع false لو انتهى الوقت أو انسكّر الاتصال.
static bool upReadLine(String& out, unsigned long deadline) {
  out = "";
  while ((long)(millis() - deadline) < 0) {
    while (g_upClient.available()) {
      char c = (char)g_upClient.read();
      if (c == '\n') { out.trim(); return true; }
      if (out.length() < 512) out += c;
    }
    if (!g_upClient.connected()) return false;
    delay(5);
    camWdtFeed();
  }
  return false;
}

// بترجّع true لو الخادم استلم الصورة.
bool uploadSnapshot(const String& id, const uint8_t* data, size_t len) {
  ownKeyLoad();
  if (!g_hasOwnKey && g_id.sharedKey.length() == 0) {
    g_log.println("[UP] لا يوجد مفتاح توقيع — الرفع معطّل");
    return false;
  }
  if (!camValidId(id)) {
    g_log.println("[UP] معرّف طلب مرفوض");
    return false;
  }

  camSyncClock();
  if (!g_clockReady) {
    g_log.println("[UP] الساعة مش مضبوطة — التوقيع رح ينرفض، بنوفّر المحاولة");
    return false;
  }

  const String bodyHash = sha256Hex(data, len);

  // اتصال محفوظ ممكن يكون الخادم سكّره من طرفه بينما كنّا ساكتين. أول إرسال
  // عليه بيفشل؛ فبنجرّب مرّة كمان ع اتصال جديد قبل ما نقول فشلنا.
  for (int attempt = 0; attempt < 2; attempt++) {
    if (!upEnsureConnected()) return false;

    // الوقت بالميلي ثانية منذ الحقبة — الخادم بيرفض أي طلب أقدم من دقيقتين.
    char ts[24];
    snprintf(ts, sizeof(ts), "%llu", (unsigned long long)time(nullptr) * 1000ULL);
    String node = camNodeId();
    String sig = hmacHex(node + id + ts + bodyHash);

    String head =
        "POST /api/cam/upload HTTP/1.1\r\n"
        "Host: " + String(SANDY_UPLOAD_HOST) + "\r\n"
        "Content-Type: image/jpeg\r\n"
        "Content-Length: " + String(len) + "\r\n"
        "X-Sandy-Node: " + node + "\r\n"
        "X-Sandy-Req: " + id + "\r\n"
        "X-Sandy-Ts: " + String(ts) + "\r\n"
        "X-Sandy-Sig: " + sig + "\r\n"
        "X-Sandy-Body-Sha256: " + bodyHash + "\r\n" +
        (g_hasOwnKey ? String("X-Sandy-Kv: 2\r\n") : String("")) +
        "Connection: keep-alive\r\n\r\n";
    if (g_upClient.print(head) != head.length()) {
      g_upClient.stop();
      continue;                                  // اتصال قديم مات — جديد
    }

    // بندفع الصورة بقطع بحجم حزمة الشبكة ع نفس الاتصال.
    const size_t STEP = 1460;
    size_t sent = 0;
    bool broken = false;
    while (sent < len) {
      size_t n = (len - sent > STEP) ? STEP : (len - sent);
      size_t w = g_upClient.write(data + sent, n);
      if (w == 0) { broken = true; break; }
      sent += w;
      camWdtFeed();
      delay(1);
    }
    if (broken) {
      g_log.printf("[UP] انقطع الإرسال عند %u من %u\n", (unsigned)sent, (unsigned)len);
      g_upClient.stop();
      if (sent == 0) continue;                   // ما وصل ولا بايت — جرّب ع جديد
      return false;
    }

    // سطر الحالة → الرقم، مش «فيه ٢٠٠ بمكان ما».
    unsigned long deadline = millis() + 15000;
    String line;
    if (!upReadLine(line, deadline)) {
      g_log.println("[UP] الخادم ما ردّ");
      g_upClient.stop();
      return false;
    }
    int sp = line.indexOf(' ');
    int code = sp > 0 ? line.substring(sp + 1, sp + 4).toInt() : 0;

    // الترويسات لحدّ السطر الفاضي، ومنها طول الجسم وإذا الاتصال رح يضلّ مفتوح.
    long contentLength = -1;
    bool serverCloses = false;
    while (upReadLine(line, deadline)) {
      if (line.length() == 0) break;
      String low = line;
      low.toLowerCase();
      if (low.startsWith("content-length:")) contentLength = low.substring(15).toInt();
      else if (low.startsWith("connection:") && low.indexOf("close") > 0) serverCloses = true;
    }

    // الجسم — فيه مفتاحنا لو الخادم بعته. محدود بالحجم والوقت.
    String body;
    long want = contentLength >= 0 ? contentLength : 1024;
    if (want > 1024) want = 1024;
    while ((long)body.length() < want && (long)(millis() - deadline) < 0) {
      if (g_upClient.available()) body += (char)g_upClient.read();
      else if (!g_upClient.connected()) break;
      else delay(5);
    }
    if (serverCloses || contentLength < 0) g_upClient.stop();

    bool ok = code == 200;
    if (!ok) g_log.printf("[UP] ردّ الخادم: %d\n", code);
    if (ok && !g_hasOwnKey) {
      // متسامح مع المسافات: `"device_key": "…"` و`"device_key":"…"` نفس الإشي.
      int at = body.indexOf("\"device_key\"");
      int colon = at >= 0 ? body.indexOf(':', at) : -1;
      int q = colon >= 0 ? body.indexOf('"', colon) : -1;
      if (q >= 0) ownKeyStore(body.substring(q + 1, q + 1 + 64));
    } else if (code == 401 && g_hasOwnKey) {
      // أي رفض توقيع بمفتاحنا الخاص معناه إنّ الخادم ما عاد بيعرفه (انفكّ
      // الاقتران، أو تدوّر المفتاح). كان بس «key_unknown» بيمسحه، فمفتاح متدوّر
      // كان بيوقف الرفع للأبد.
      ownKeyDrop();
    }
    return ok;
  }
  return false;
}
