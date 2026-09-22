// =========================
// Sandy — هويّة اللوح (الكاميرا وعقدة الغرفة)
// =========================
//
// **نسخة طبق الأصل بـ vision-core و room-node** (اختبار بيتأكّد).
//
// كود الاقتران ومفاتيح الوسيط والشبكة كانوا محروقين جوّا البرنامج نفسه. هاد
// ماشي طول ما كل لوح بينحرق بالكيبل لحاله — وبيوقف أول ما صار في تحديث عن بعد:
// صورة وحدة بتنزل لكل الروبوتات، فإمّا بتحمل هويّة روبوت واحد لكل الباقيين،
// أو بتمسح هويّاتهم. والصورة ع الخادم عامّة، فأي سرّ فيها مكشوف.
//
// هلّق الهويّة بتعيش بذاكرة اللوح الدائمة (`sandyid`):
//   • حرق بالكيبل بقيم حقيقية بـ secrets.h ← بتنكتب بالذاكرة وبتنستعمل.
//   • صورة التحديث (مبنية بـ secrets.example.h، قيم أمثلة) ← الذاكرة هي المرجع.
// كل حقل لحاله: قيمة مثال ما بتمسح قيمة محفوظة أبدًا.

#ifndef SANDY_IDENTITY_H
#define SANDY_IDENTITY_H

#include <Preferences.h>

#define SANDY_ID_NVS "sandyid"

struct SandyIdentity {
  String pair;        // كود الاقتران المطبوع ع العلبة
  String mqttHost;    // الوسيط — بيتغيّر لو انتقلنا لوسيط تاني، فمكانه هون مش بالصورة
  String mqttUser;
  String mqttPass;
  String sharedKey;   // مفتاح الرفع المشترك (الكاميرا بس) — لحدّ ما ياخد مفتاحه الخاص
  String wifiSsid;    // الشبكة الأولى
  String wifiPass;
  bool complete() const {
    return pair.length() && mqttHost.length() && mqttUser.length() && mqttPass.length();
  }
};

static SandyIdentity g_id;

// قيمة مثال = مش قيمة. «YOUR_…» و«…XXXX…» هنّ اللي بملفات المثال.
static bool sandyIsPlaceholder(const char* v) {
  return v == nullptr || *v == '\0' || strncmp(v, "YOUR_", 5) == 0 ||
         strstr(v, "XXXX") != nullptr;
}

static String sandyIdField(Preferences* p, const char* key, const char* compiled) {
  if (!sandyIsPlaceholder(compiled)) {
    if (p && p->getString(key, "") != compiled) p->putString(key, compiled);
    return String(compiled);
  }
  return p ? p->getString(key, "") : String();
}

static void sandyIdentityLoad(const char* pair, const char* mqttHost,
                              const char* mqttUser, const char* mqttPass,
                              const char* sharedKey, const char* wifiSsid,
                              const char* wifiPass) {
  Preferences prefs;
  Preferences* p = prefs.begin(SANDY_ID_NVS, false) ? &prefs : nullptr;
  g_id.pair      = sandyIdField(p, "pair", pair);
  g_id.mqttHost  = sandyIdField(p, "mh", mqttHost);
  g_id.mqttUser  = sandyIdField(p, "mu", mqttUser);
  g_id.mqttPass  = sandyIdField(p, "mp", mqttPass);
  g_id.sharedKey = sandyIdField(p, "sk", sharedKey);
  g_id.wifiSsid  = sandyIdField(p, "ws", wifiSsid);
  // كلمة سرّ الشبكة ممكن تكون فاضية ع شبكة مفتوحة؛ بتمشي مع اسمها.
  if (!sandyIsPlaceholder(wifiSsid)) g_id.wifiPass = sandyIdField(p, "wp", wifiPass ? wifiPass : "");
  else g_id.wifiPass = p ? p->getString("wp", "") : String();
  if (p) prefs.end();

  if (g_id.complete()) {
    Serial.printf("[ID] كود %s — الهويّة جاهزة\n", g_id.pair.c_str());
  } else {
    // ما بنخمّن ولا بنتصل بهويّة ناقصة: لوح بلا كود بيسمع ع شجرة غلط.
    Serial.println("[ID] ⚠️ ما في هويّة — لازم حرق أوّل بالكيبل بقيم secrets.h الحقيقية");
  }
}

#endif  // SANDY_IDENTITY_H
