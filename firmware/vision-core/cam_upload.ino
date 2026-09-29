// رفع الصورة للخادم مباشرة بطلب HTTPS واحد (الوسيط بيضيّع قطع الصور بصمت).
// التوثيق زي مقبس الصوت: توقيع بمفتاح مشترك ع (الوحدة + الطلب + الوقت)، والوقت بيمنع الإعادة.

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

// القيم الافتراضية بـ config.h.

// الساعة شرط للرفع: الخادم بيرفض طلب أقدم من دقيقتين (ساعة سنة سبعين = 400).
// بتستنّى عشر ثواني بحد أقصى.
static bool g_clockReady = false;
// قبل هالتاريخ الساعة مش مضبوطة.
#define CAM_CLOCK_SANE_EPOCH 1700000000

void camSyncClock() {
  if (g_clockReady) return;
  // الراوتر أول (شبكات كتير بتحجب خدمة الوقت العامة)، بعدين الخدمات العامة.
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

// مفتاح الكاميرا الخاص: بعد الاقتران الخادم بيردّ ع رفع موقّع بالمشترك بمفتاح خاص،
// بينخزّن وبيوقّع كل رفع بعده (والخادم بيرفض المشترك بعدها). «key_unknown» بيمسحه.
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

// بصمة الصورة داخلة بالتوقيع.
static String sha256Hex(const uint8_t* data, size_t len) {
  uint8_t out[32];
  mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), data, len, out);
  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + i * 2, "%02x", out[i]);
  hex[64] = '\0';
  return String(hex);
}

// ── البثّ البعيد ──
// إطار كل تلت ثانية بيترفع للخادم والتطبيق بيسحبه: بيشتغل من برّا البيت بلا منفذ مفتوح.
static bool g_remoteStream = false;
static unsigned long g_remoteNextMs = 0;
static unsigned long g_remoteUntilMs = 0;

void camRemoteStream(bool on) {
  g_remoteStream = on;
  g_remoteNextMs = 0;
  // مهلة خمس دقايق: بثّ منسي كان يحجز الحلقة ويمنع الترقية.
  g_remoteUntilMs = on ? millis() + CAM_REMOTE_STREAM_MAX_MS : 0;
  g_log.printf("[UP] البثّ البعيد %s\n", on ? "اشتغل" : "وقف");
}

bool camRemoteStreaming() { return g_remoteStream; }

// من الحلقة الرئيسية: إطار واحد لمّا يحين وقته.
void camRemoteStreamTick() {
  if (!g_remoteStream || !g_cameraReady) return;

  if (g_remoteUntilMs && (long)(millis() - g_remoteUntilMs) > 0) {
    g_log.println("[UP] البثّ البعيد وقف لحاله — انتهت المهلة");
    camRemoteStream(false);
    return;
  }

  // مخزن إطار واحد: المتفرّج المحلي أولى.
  if (g_streamViewerActive) return;

  if (g_remoteNextMs && (long)(millis() - g_remoteNextMs) < 0) return;
  g_remoteNextMs = millis() + CAM_REMOTE_STREAM_INTERVAL_MS;

  if (!camLock(200)) return;   // المستشعر مشغول بلقطة — الإطار الجاي
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    camUnlock();
    // المستشعر لسا بيسلّم مخزنه بعد بثّ محلي: الدورة الجاية.
    g_log.println("[UP] المستشعر مش جاهز — بنأجّل الإطار");
    return;
  }
  // معرّف ثابت: الإطار الجديد بيستبدل القديم ع الخادم.
  bool ok = uploadSnapshot("live", fb->buf, fb->len);
  esp_camera_fb_return(fb);
  camUnlock();
  if (!ok) {
    // فشل إطار واحد ما بيوقّف البث.
    g_log.println("[UP] إطار ضاع");
  }
}

// اتصال واحد مفتوح: مصافحة لكل صورة كانت تقطّع الذاكرة الداخلية لحدّ فشل التخصيص.
static WiFiClientSecure g_upClient;
static bool g_upClientReady = false;

// قبل التحديث: التنزيل بدّه ذاكرة التشفير.
void camUploadClose() {
  g_upClient.stop();
}

static bool upEnsureConnected() {
  if (g_upClient.connected()) return true;
  g_upClient.stop();
  if (!g_upClientReady) {
    // جذور قصيرة (sandy_ca_roots.h)؛ بلا تحقّق أي حدا ع الشبكة بياخد الصور والمفتاح.
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

// false لو انتهى الوقت أو انسكّر الاتصال.
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

// true لو الخادم استلم.
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

  // الاتصال المحفوظ ممكن الخادم سكّره: محاولة تانية ع اتصال جديد.
  for (int attempt = 0; attempt < 2; attempt++) {
    if (!upEnsureConnected()) return false;

    // ms منذ الحقبة.
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

    // قطع بحجم حزمة الشبكة.
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

    // سطر الحالة → الرقم.
    unsigned long deadline = millis() + 15000;
    String line;
    if (!upReadLine(line, deadline)) {
      g_log.println("[UP] الخادم ما ردّ");
      g_upClient.stop();
      return false;
    }
    int sp = line.indexOf(' ');
    int code = sp > 0 ? line.substring(sp + 1, sp + 4).toInt() : 0;

    // الترويسات: طول الجسم وإذا الاتصال بيضل مفتوح.
    long contentLength = -1;
    bool serverCloses = false;
    while (upReadLine(line, deadline)) {
      if (line.length() == 0) break;
      String low = line;
      low.toLowerCase();
      if (low.startsWith("content-length:")) contentLength = low.substring(15).toInt();
      else if (low.startsWith("connection:") && low.indexOf("close") > 0) serverCloses = true;
    }

    // الجسم (فيه مفتاحنا لو انبعت)، محدود بالحجم والوقت.
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
      // متسامح مع المسافات.
      int at = body.indexOf("\"device_key\"");
      int colon = at >= 0 ? body.indexOf(':', at) : -1;
      int q = colon >= 0 ? body.indexOf('"', colon) : -1;
      if (q >= 0) ownKeyStore(body.substring(q + 1, q + 1 + 64));
    } else if (code == 401 && g_hasOwnKey) {
      // أي رفض لمفتاحنا الخاص (انفكّ الاقتران أو تدوّر) بيمسحه.
      ownKeyDrop();
    }
    return ok;
  }
  return false;
}
