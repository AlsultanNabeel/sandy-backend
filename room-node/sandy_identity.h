// Sandy — هويّة اللوح (الكاميرا وعقدة الغرفة). نسخة طبق الأصل بـ vision-core و room-node (اختبار بيتأكّد).
// الهويّة بذاكرة اللوح (`sandyid`) مش بالصورة: حرق الكيبل بقيم secrets.h الحقيقية
// بيكتبها، وصورة التحديث (secrets.example.h) بتقرا المحفوظ. قيمة مثال ما بتمسح المحفوظ.

#ifndef SANDY_IDENTITY_H
#define SANDY_IDENTITY_H

#include <Preferences.h>

#define SANDY_ID_NVS "sandyid"

struct SandyIdentity {
  String pair;        // كود الاقتران المطبوع ع العلبة
  String mqttHost;    // الوسيط، مش بالصورة
  String mqttUser;
  String mqttPass;
  String sharedKey;   // مفتاح الرفع المشترك (الكاميرا بس) لحدّ ما ياخد الخاص
  String wifiSsid;    // الشبكة الأولى
  String wifiPass;
  bool complete() const {
    return pair.length() && mqttHost.length() && mqttUser.length() && mqttPass.length();
  }
};

static SandyIdentity g_id;

// «YOUR_…» و«…XXXX…» = قيم أمثلة.
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
  // كلمة السر ممكن تكون فاضية (شبكة مفتوحة).
  if (!sandyIsPlaceholder(wifiSsid)) g_id.wifiPass = sandyIdField(p, "wp", wifiPass ? wifiPass : "");
  else g_id.wifiPass = p ? p->getString("wp", "") : String();
  if (p) prefs.end();

  if (g_id.complete()) {
    Serial.printf("[ID] كود %s — الهويّة جاهزة\n", g_id.pair.c_str());
  } else {
    // ما منتصل بهويّة ناقصة.
    Serial.println("[ID] ⚠️ ما في هويّة — لازم حرق أوّل بالكيبل بقيم secrets.h الحقيقية");
  }
}

#endif  // SANDY_IDENTITY_H
