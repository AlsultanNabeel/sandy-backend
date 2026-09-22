// =========================
// Sandy — التحديث عن بعد للألواح الصغيرة (الكاميرا وعقدة الغرفة)
// =========================
//
// **نسخة طبق الأصل بـ vision-core و room-node.** اختبار بالمستودع بيتأكّد
// إنّ النسختين متطابقتين، ف أي تعديل لازم ينعمل بالاتنين.
//
// نفس فكرة الدماغ (firmware/brain-core/main/sandy_ota.c) بالضبط:
//
//   ١. اللوح بيسأل الخادم: `/api/firmware/manifest?board=<لوح>&device_id=&v=`.
//      الروبوت المباع ورا راوتر حدا تاني، ما حدا بيقدر يوصله — فهو اللي بيسأل.
//   ٢. التوقيع (ECDSA P-256) بيتفحص بالمفتاح العام المحروق هون. الرسالة
//      الموقّعة فيها اسم اللوح: `sandy-fw|<لوح>|<نسخة>|<حجم>|<sha256>` — فصورة
//      الدماغ الموقّعة ما بتنركّب ع كاميرا حتى لو الخادم غلط أو انخرق.
//   ٣. الصورة بتنزل ع القسم الفاضي، والبصمة بتنحسب وهي نازلة، وما بنبدّل
//      القسم إلا لو الحجم والبصمة طابقوا الموقّع.
//   ٤. بعد الإقلاع الجديد الصورة «تحت التجربة»: لو ما رجع اللوح ع الوسيط خلال
//      خمس دقايق، أو علّق وقام المراقب، بيرجع للنسخة القديمة لحاله. والنسخة
//      اللي فشلت بتنحفظ وما بنرجع نجرّبها.
//
// ما في نزول لنسخة أقدم أبدًا.

#ifndef SANDY_OTA_PULL_H
#define SANDY_OTA_PULL_H

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <Update.h>
#include <Preferences.h>
#include "esp_ota_ops.h"
#include "mbedtls/md.h"
#include "mbedtls/pk.h"

// المفتاح العام — نفس firmware/brain-core/main/fw_pubkey.pem. عام، مش سرّ:
// بيفحص التوقيع بس، وما بيقدر يوقّع.
static const char SANDY_FW_PUBKEY[] =
  "-----BEGIN PUBLIC KEY-----\n"
  "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE3DWyfwXCt1A8SsoVVx/wB/tiZqNJ\n"
  "3/wa1fmOeN4VYuaM+OcYHV6FrOIIL9kKKhIJtCo91WiTachk4o773xd8kw==\n"
  "-----END PUBLIC KEY-----\n";

#define SANDY_OTA_FIRST_CHECK_MS  (2UL * 60UL * 1000UL)          // دقيقتين بعد الشبكة
#define SANDY_OTA_PERIOD_MS       (6UL * 60UL * 60UL * 1000UL)   // كل ست ساعات
#define SANDY_OTA_RETRY_MS        (15UL * 60UL * 1000UL)         // اللوح كان مشغول أو الخادم ما ردّ
#define SANDY_OTA_HEALTH_MS       (60UL * 1000UL)                // دقيقة ع الوسيط = الصورة سليمة
#define SANDY_OTA_HEALTH_LIMIT_MS (5UL * 60UL * 1000UL)          // خمس دقايق بلا وسيط = رجوع
#define SANDY_OTA_NET_TIMEOUT_MS  15000
#define SANDY_OTA_MANIFEST_MAX    1024
#define SANDY_OTA_BUF             2048
#define SANDY_OTA_NVS             "sandyota"

struct SandyOtaConfig {
  const char* board;          // "cam" | "room" — نفس أسماء الخادم
  const char* host;           // خادم ساندي
  const char* deviceId;       // معرّف العقدة
  const char* version;        // نسخة هالصورة
  const char* caRoots;        // جذور الشهادات
  bool (*idle)();             // اللوح فاضي؟ (مش بيصوّر، مش بيحرّك)
  void (*prepare)();          // حرّر الذاكرة قبل التنزيل (مثلًا سكّر اتصالات)
  void (*feed)();             // غذّي المراقب وقت التنزيل
};

static SandyOtaConfig g_otaCfg;
static unsigned long  g_otaNextCheckMs = 0;
static bool           g_otaPendingVerify = false;
static unsigned long  g_otaHealthySinceMs = 0;

// أرويدوينو بيعلّم أي صورة جديدة «سليمة» لحظة الإقلاع، قبل ما نعرف إذا بتوصل
// الشبكة أصلًا. هيك بنأجّل الحكم: الصورة بتضلّ تحت التجربة لحدّ ما تثبت حالها.
// (دالّة C بالنواة، فالاسم لازم يطلع بلا تزيين C++ وإلا ما بتنربط وبتنتجاهل بصمت.)
extern "C" bool verifyRollbackLater() { return true; }

// -1 / 0 / 1 رقميًّا لكل جزء ("0.10" أكبر من "0.9").
static int sandyOtaVersionCmp(const char* a, const char* b) {
  for (int part = 0; part < 8; part++) {
    char *ea, *eb;
    long x = strtol(a, &ea, 10), y = strtol(b, &eb, 10);
    if (x != y) return x < y ? -1 : 1;
    bool endA = (*ea != '.'), endB = (*eb != '.');
    if (endA && endB) break;
    a = endA ? ea : ea + 1;
    b = endB ? eb : eb + 1;
  }
  return 0;
}

static bool sandyOtaJsonStr(const String& js, const char* key, char* out, size_t cap) {
  String pat = String("\"") + key + "\"";
  int p = js.indexOf(pat);
  if (p < 0) return false;
  p = js.indexOf(':', p + pat.length());
  if (p < 0) return false;
  p++;
  while (p < (int)js.length() && js[p] == ' ') p++;
  if (p >= (int)js.length() || js[p] != '"') return false;
  p++;
  size_t j = 0;
  while (p < (int)js.length() && js[p] != '"' && j + 1 < cap) out[j++] = js[p++];
  out[j] = '\0';
  return p < (int)js.length() && js[p] == '"' && j > 0;
}

static long sandyOtaJsonNum(const String& js, const char* key) {
  String pat = String("\"") + key + "\"";
  int p = js.indexOf(pat);
  if (p < 0) return -1;
  p = js.indexOf(':', p + pat.length());
  if (p < 0) return -1;
  return strtol(js.c_str() + p + 1, nullptr, 10);
}

static size_t sandyOtaUnhex(const char* hex, unsigned char* out, size_t cap) {
  size_t len = strlen(hex);
  if (len % 2 || len / 2 > cap) return 0;
  for (size_t i = 0; i < len / 2; i++) {
    unsigned v;
    if (sscanf(hex + 2 * i, "%2x", &v) != 1) return 0;
    out[i] = (unsigned char)v;
  }
  return len / 2;
}

static bool sandyOtaSignatureOk(const char* version, long size, const char* sha,
                                const char* sigHex) {
  char msg[192];
  int n = snprintf(msg, sizeof(msg), "sandy-fw|%s|%s|%ld|%s",
                   g_otaCfg.board, version, size, sha);
  if (n <= 0 || n >= (int)sizeof(msg)) return false;
  unsigned char hash[32], sig[80];
  size_t sigLen = sandyOtaUnhex(sigHex, sig, sizeof(sig));
  if (!sigLen) return false;
  if (mbedtls_md(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256),
                 (const unsigned char*)msg, (size_t)n, hash) != 0) return false;
  mbedtls_pk_context pk;
  mbedtls_pk_init(&pk);
  int r = mbedtls_pk_parse_public_key(&pk, (const unsigned char*)SANDY_FW_PUBKEY,
                                      sizeof(SANDY_FW_PUBKEY));
  if (r == 0) r = mbedtls_pk_verify(&pk, MBEDTLS_MD_SHA256, hash, sizeof(hash), sig, sigLen);
  mbedtls_pk_free(&pk);
  return r == 0;
}

// طلب GET بسيط. بيرجّع رمز الحالة والطول، والعميل واقف عند أول بايت بالجسم.
static int sandyOtaGet(WiFiClientSecure& c, const String& path, long* contentLength) {
  *contentLength = -1;
  if (!c.connect(g_otaCfg.host, 443)) return -1;
  c.print(String("GET ") + path + " HTTP/1.1\r\nHost: " + g_otaCfg.host +
          "\r\nUser-Agent: sandy-" + g_otaCfg.board + "/" + g_otaCfg.version +
          "\r\nConnection: close\r\n\r\n");
  String line = c.readStringUntil('\n');
  int sp = line.indexOf(' ');
  if (!line.startsWith("HTTP/1.") || sp < 0) return -1;
  int status = line.substring(sp + 1, sp + 4).toInt();
  while (c.connected() || c.available()) {
    String h = c.readStringUntil('\n');
    h.trim();
    if (h.length() == 0) break;
    String lower = h;
    lower.toLowerCase();
    if (lower.startsWith("content-length:")) *contentLength = h.substring(15).toInt();
  }
  return status;
}

static bool sandyOtaIsBad(const char* version) {
  Preferences p;
  if (!p.begin(SANDY_OTA_NVS, true)) return false;
  String bad = p.getString("bad", "");
  p.end();
  return bad.length() && bad == version;
}

// الفحص الكامل. بيرجّع لمتى نأجّل الفحص الجاي.
static unsigned long sandyOtaCheckOnce() {
  char path[200];
  snprintf(path, sizeof(path), "/api/firmware/manifest?board=%s&device_id=%s&v=%s",
           g_otaCfg.board, g_otaCfg.deviceId, g_otaCfg.version);

  WiFiClientSecure c;
  c.setCACert(g_otaCfg.caRoots);
  c.setTimeout(SANDY_OTA_NET_TIMEOUT_MS);
  c.setHandshakeTimeout(SANDY_OTA_NET_TIMEOUT_MS / 1000);
  long len;
  int status = sandyOtaGet(c, path, &len);
  if (status == 204) {
    c.stop();
    Serial.printf("[OTA] %s محدّث\n", g_otaCfg.version);
    return SANDY_OTA_PERIOD_MS;
  }
  if (status != 200 || len <= 0 || len > SANDY_OTA_MANIFEST_MAX) {
    c.stop();
    Serial.printf("[OTA] الفحص فشل: HTTP %d\n", status);
    return SANDY_OTA_RETRY_MS;
  }
  String js;
  js.reserve(len);
  unsigned long t0 = millis();
  while ((long)js.length() < len && millis() - t0 < SANDY_OTA_NET_TIMEOUT_MS) {
    while (c.available() && (long)js.length() < len) js += (char)c.read();
    if (!c.connected() && !c.available()) break;
    delay(5);
  }
  c.stop();

  char version[24], sha[65], sig[161], url[96];
  long size = sandyOtaJsonNum(js, "size");
  if (!sandyOtaJsonStr(js, "version", version, sizeof(version)) ||
      !sandyOtaJsonStr(js, "sha256", sha, sizeof(sha)) ||
      !sandyOtaJsonStr(js, "signature", sig, sizeof(sig)) ||
      !sandyOtaJsonStr(js, "url", url, sizeof(url)) || size <= 0 || url[0] != '/') {
    Serial.println("[OTA] بيان غير مقروء");
    return SANDY_OTA_RETRY_MS;
  }
  if (sandyOtaVersionCmp(version, g_otaCfg.version) <= 0) return SANDY_OTA_PERIOD_MS;
  if (sandyOtaIsBad(version)) {
    Serial.printf("[OTA] %s فشلت قبل هيك — ما بنعيدها\n", version);
    return SANDY_OTA_PERIOD_MS;
  }
  if (!sandyOtaSignatureOk(version, size, sha, sig)) {
    Serial.printf("[OTA] %s: التوقيع مش سليم — مرفوضة\n", version);
    return SANDY_OTA_PERIOD_MS;
  }
  const esp_partition_t* slot = esp_ota_get_next_update_partition(nullptr);
  if (!slot || size > (long)slot->size) {
    Serial.printf("[OTA] %s: ما بتساع بالقسم (%ld)\n", version, size);
    return SANDY_OTA_PERIOD_MS;
  }

  Serial.printf("[OTA] %s موقّعة — بننزّل %ld بايت\n", version, size);
  if (g_otaCfg.prepare) g_otaCfg.prepare();

  status = sandyOtaGet(c, url, &len);
  if (status != 200 || (len >= 0 && len != size)) {
    c.stop();
    Serial.printf("[OTA] التنزيل ما بلّش: HTTP %d\n", status);
    return SANDY_OTA_RETRY_MS;
  }
  if (!Update.begin(size)) {
    c.stop();
    Serial.printf("[OTA] ما قدرنا نفتح القسم: %s\n", Update.errorString());
    return SANDY_OTA_RETRY_MS;
  }

  uint8_t* buf = (uint8_t*)malloc(SANDY_OTA_BUF);
  mbedtls_md_context_t md;
  mbedtls_md_init(&md);
  bool fail = buf == nullptr ||
              mbedtls_md_setup(&md, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 0) != 0 ||
              mbedtls_md_starts(&md) != 0;
  long total = 0;
  unsigned long lastByte = millis();
  while (!fail && total < size) {
    if (g_otaCfg.feed) g_otaCfg.feed();
    int avail = c.available();
    if (avail <= 0) {
      if (!c.connected() || millis() - lastByte > SANDY_OTA_NET_TIMEOUT_MS) { fail = true; break; }
      delay(2);
      continue;
    }
    long want = size - total;
    if (want > SANDY_OTA_BUF) want = SANDY_OTA_BUF;
    if (want > avail) want = avail;
    int n = c.read(buf, (size_t)want);
    if (n <= 0) continue;
    lastByte = millis();
    if (mbedtls_md_update(&md, buf, (size_t)n) != 0 || Update.write(buf, n) != (size_t)n) {
      fail = true;
      break;
    }
    total += n;
  }
  c.stop();
  free(buf);

  unsigned char digest[32] = {0};
  char digestHex[65] = {0};
  if (!fail && mbedtls_md_finish(&md, digest) != 0) fail = true;
  mbedtls_md_free(&md);
  for (int i = 0; i < 32; i++) snprintf(digestHex + 2 * i, 3, "%02x", digest[i]);

  if (fail || total != size || strcasecmp(digestHex, sha) != 0) {
    Update.abort();
    Serial.printf("[OTA] %s: اللي نزل مش هو الموقّع — انرمى\n", version);
    return SANDY_OTA_RETRY_MS;
  }
  if (!Update.end(true)) {
    Serial.printf("[OTA] %s: ما انقفل التحديث: %s\n", version, Update.errorString());
    return SANDY_OTA_RETRY_MS;
  }
  // منحفظ شو جرّبنا: لو رجعنا للقديمة، الإقلاع الجاي بيعرف إنها هي اللي فشلت.
  Preferences p;
  if (p.begin(SANDY_OTA_NVS, false)) {
    p.putString("trying", version);
    p.end();
  }
  Serial.printf("[OTA] %s جاهزة — إعادة تشغيل\n", version);
  delay(200);
  ESP.restart();
  return SANDY_OTA_PERIOD_MS;
}

// بالإقلاع: هل هالصورة جديدة تحت التجربة؟ وهل نسخة سابقة فشلت ورجعنا منها؟
static void sandyOtaBegin(const SandyOtaConfig& cfg) {
  g_otaCfg = cfg;
  g_otaNextCheckMs = millis() + SANDY_OTA_FIRST_CHECK_MS;

  esp_ota_img_states_t st;
  const esp_partition_t* running = esp_ota_get_running_partition();
  g_otaPendingVerify = running && esp_ota_get_state_partition(running, &st) == ESP_OK &&
                       st == ESP_OTA_IMG_PENDING_VERIFY;

  Preferences p;
  if (!p.begin(SANDY_OTA_NVS, false)) return;
  String trying = p.getString("trying", "");
  if (trying.length() && trying != cfg.version) {
    // جرّبنا نسخة ورجعنا للقديمة: هي اللي فشلت.
    p.putString("bad", trying);
    Serial.printf("[OTA] %s فشلت ورجعنا لـ %s\n", trying.c_str(), cfg.version);
  }
  if (trying.length()) p.remove("trying");
  p.end();
  if (g_otaPendingVerify) Serial.printf("[OTA] %s تحت التجربة\n", cfg.version);
}

// من الحلقة. `online` = اللوح موصول ع الوسيط هلّق.
static void sandyOtaLoop(bool online) {
  unsigned long now = millis();
  if (g_otaPendingVerify) {
    if (online) {
      if (!g_otaHealthySinceMs) g_otaHealthySinceMs = now ? now : 1;
      if (now - g_otaHealthySinceMs >= SANDY_OTA_HEALTH_MS) {
        esp_ota_mark_app_valid_cancel_rollback();
        g_otaPendingVerify = false;
        Serial.printf("[OTA] %s ثبتت — صارت النسخة المعتمدة\n", g_otaCfg.version);
      }
    } else {
      g_otaHealthySinceMs = 0;
      if (now >= SANDY_OTA_HEALTH_LIMIT_MS) {
        Serial.println("[OTA] الصورة الجديدة ما وصلت الوسيط — رجوع للقديمة");
        esp_ota_mark_app_invalid_rollback_and_reboot();
      }
    }
    return;   // ما في تحديث جديد قبل ما هاد يثبت
  }
  if (!online || (long)(now - g_otaNextCheckMs) < 0) return;
  if (g_otaCfg.idle && !g_otaCfg.idle()) {
    g_otaNextCheckMs = now + 30000UL;   // مشغول — بنرجع بعد نص دقيقة
    return;
  }
  g_otaNextCheckMs = now + sandyOtaCheckOnce();
}

#endif  // SANDY_OTA_PULL_H
