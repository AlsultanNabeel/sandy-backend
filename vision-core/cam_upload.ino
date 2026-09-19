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

// نفس مفتاح مقبس الصوت — بينحطّ بـ secrets.h
#ifndef SANDY_WS_HMAC_KEY
#define SANDY_WS_HMAC_KEY ""
#endif
#ifndef SANDY_UPLOAD_HOST
#define SANDY_UPLOAD_HOST "sandy-robot-3da0693d32f7.herokuapp.com"
#endif

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

void camSyncClock() {
  if (g_clockReady) return;
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  unsigned long deadline = millis() + 10000;
  while (millis() < deadline) {
    if (time(nullptr) > 1700000000) {   // أي وقت معقول بعد ٢٠٢٣
      g_clockReady = true;
      g_log.println("[TIME] الساعة انضبطت");
      return;
    }
    delay(200);
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
  const unsigned char* key = g_hasOwnKey ? g_ownKey : (const unsigned char*)SANDY_WS_HMAC_KEY;
  size_t keyLen = g_hasOwnKey ? sizeof(g_ownKey) : strlen(SANDY_WS_HMAC_KEY);
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

  if (g_remoteUntilMs && millis() > g_remoteUntilMs) {
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

  if (millis() < g_remoteNextMs) return;
  g_remoteNextMs = millis() + CAM_REMOTE_STREAM_INTERVAL_MS;

  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    // إطار فاضي بعد بثّ محلي: المستشعر لسا بيسلّم مخزنه. نجرّب بالدورة الجاية
    // بدل ما نلحّ عليه ونخلّيه أسوأ.
    g_log.println("[UP] المستشعر مش جاهز — بنأجّل الإطار");
    return;
  }
  // معرّف ثابت: الإطار الجديد بيستبدل القديم بصندوق الخادم بدل ما يتراكم.
  // بثّ بيخزّن كل إطار بيملا القرص بدقايق، والمشاهد بده الأحدث وبس.
  bool ok = uploadSnapshot("live", fb->buf, fb->len);
  esp_camera_fb_return(fb);
  if (!ok) {
    // فشل إطار واحد ما بيوقّف البثّ — الشبكة بتتعثّر، والمشاهد بيشوف تهنيقة
    // بدل ما ينقطع كل إشي. بس لو تعثّرت كتير، بتبان بالسجل.
    g_log.println("[UP] إطار ضاع");
  }
}

// بترجّع true لو الخادم استلم الصورة.
bool uploadSnapshot(const String& id, const uint8_t* data, size_t len) {
  ownKeyLoad();
  if (!g_hasOwnKey && strlen(SANDY_WS_HMAC_KEY) == 0) {
    g_log.println("[UP] لا يوجد مفتاح توقيع — الرفع معطّل");
    return false;
  }

  camSyncClock();
  if (!g_clockReady) {
    g_log.println("[UP] الساعة مش مضبوطة — التوقيع رح ينرفض، بنوفّر المحاولة");
    return false;
  }

  WiFiClientSecure client;
  // بنتحقّق من شهادة الخادم بقائمة جذور قصيرة (sandy_ca_roots.h) — المخزن
  // الكامل ما بيسع، بس خمس جذور بيسعوا. بلا تحقّق، أي حدا ع نفس الشبكة بياخد
  // صور البيت ومفتاح الكاميرا.
  client.setCACert(SANDY_CA_ROOTS);
  client.setTimeout(15000);

  if (!client.connect(SANDY_UPLOAD_HOST, 443)) {
    g_log.println("[UP] فشل الاتصال بالخادم");
    return false;
  }

  // الوقت بالميلي ثانية منذ الحقبة — الخادم بيرفض أي طلب أقدم من دقيقتين.
  char ts[24];
  snprintf(ts, sizeof(ts), "%llu", (unsigned long long)time(nullptr) * 1000ULL);
  String node = camNodeId();
  String sig = hmacHex(node + id + ts);

  String head =
      "POST /api/cam/upload HTTP/1.1\r\n"
      "Host: " + String(SANDY_UPLOAD_HOST) + "\r\n"
      "Content-Type: image/jpeg\r\n"
      "Content-Length: " + String(len) + "\r\n"
      "X-Sandy-Node: " + node + "\r\n"
      "X-Sandy-Req: " + id + "\r\n"
      "X-Sandy-Ts: " + String(ts) + "\r\n"
      "X-Sandy-Sig: " + sig + "\r\n" +
      (g_hasOwnKey ? String("X-Sandy-Kv: 2\r\n") : String("")) +
      "Connection: close\r\n\r\n";
  client.print(head);

  // بندفع الصورة بقطع صغيرة **ع نفس الاتصال**. الفرق عن الطريقة القديمة إنّ
  // هاي قطع نقل داخلية: البروتوكول بيرتّبها ويعيد الضايع منها، وما في أي منها
  // ممكن يوصل لحاله ولا يضيع لحاله.
  const size_t STEP = 1460;   // حجم حزمة الشبكة — بلا تقسيم إضافي
  size_t sent = 0;
  while (sent < len) {
    size_t n = (len - sent > STEP) ? STEP : (len - sent);
    size_t w = client.write(data + sent, n);
    if (w == 0) {
      g_log.printf("[UP] انقطع الإرسال عند %u من %u\n", (unsigned)sent, (unsigned)len);
      client.stop();
      return false;
    }
    sent += w;
    // نفس سبب الاستدعاء بين القطع القديم: نعطي المكدّس فرصة يفضّي.
    delay(1);
  }

  // نقرا سطر الحالة. بلاه، «أرسلنا» بتصير ادّعاء مش نتيجة — وهاد بالضبط اللي
  // خلّى النشر القديم يبيّن ناجحًا وهو بيضيع.
  unsigned long deadline = millis() + 15000;
  String status;
  while (millis() < deadline && client.connected()) {
    if (client.available()) { status = client.readStringUntil('\n'); break; }
    delay(10);
  }
  // باقي الرد (ترويسات وجسم صغير) — فيه مفتاحنا لو الخادم بعته. محدود بالحجم
  // والوقت: رد غريب ما بيعلّق الرفع ولا بيعبّي الذاكرة.
  String rest;
  while (millis() < deadline && (client.connected() || client.available()) &&
         rest.length() < 1024) {
    if (client.available()) rest += (char)client.read();
    else delay(5);
  }
  client.stop();

  bool ok = status.indexOf("200") > 0;
  if (!ok) g_log.printf("[UP] ردّ الخادم: %s\n", status.c_str());
  if (ok && !g_hasOwnKey) {
    // متسامح مع المسافات: `"device_key": "…"` و`"device_key":"…"` نفس الإشي.
    int at = rest.indexOf("\"device_key\"");
    int colon = at >= 0 ? rest.indexOf(':', at) : -1;
    int q = colon >= 0 ? rest.indexOf('"', colon) : -1;
    if (q >= 0) ownKeyStore(rest.substring(q + 1, q + 1 + 64));
  } else if (!ok && g_hasOwnKey && rest.indexOf("key_unknown") >= 0) {
    ownKeyDrop();
  }
  return ok;
}
