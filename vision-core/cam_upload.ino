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
#include <time.h>

String camNodeId();

// نفس مفتاح مقبس الصوت — بينحطّ بـ secrets.h
#ifndef SANDY_WS_HMAC_KEY
#define SANDY_WS_HMAC_KEY ""
#endif
#ifndef SANDY_UPLOAD_HOST
#define SANDY_UPLOAD_HOST "sandy-robot-3da0693d32f7.herokuapp.com"
#endif

static String hmacHex(const String& msg) {
  const char* key = SANDY_WS_HMAC_KEY;
  uint8_t out[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, (const unsigned char*)key, strlen(key));
  mbedtls_md_hmac_update(&ctx, (const unsigned char*)msg.c_str(), msg.length());
  mbedtls_md_hmac_finish(&ctx, out);
  mbedtls_md_free(&ctx);

  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + i * 2, "%02x", out[i]);
  hex[64] = '\0';
  return String(hex);
}

// بترجّع true لو الخادم استلم الصورة.
bool uploadSnapshot(const String& id, const uint8_t* data, size_t len) {
  if (strlen(SANDY_WS_HMAC_KEY) == 0) {
    g_log.println("[UP] لا يوجد مفتاح توقيع — الرفع معطّل");
    return false;
  }

  WiFiClientSecure client;
  // نفس ما بيعمل مقبس الرسائل: بلا تحقّق من الشهادة. القناة مشفّرة، والتوثيق
  // بالتوقيع مش بالشهادة — ومخزن الشهادات الكامل ما بيسع بذاكرة اللوح.
  client.setInsecure();
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
      "X-Sandy-Sig: " + sig + "\r\n"
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
  client.stop();

  bool ok = status.indexOf("200") > 0;
  if (!ok) g_log.printf("[UP] ردّ الخادم: %s\n", status.c_str());
  return ok;
}
