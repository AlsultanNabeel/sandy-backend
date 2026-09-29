#pragma once
#include "esp_err.h"
#include <stdbool.h>

esp_err_t wifi_sandy_start(void);
bool      wifi_sandy_is_connected(void);

// آخر عنوان IP (أو فاضي)؛ بينبعت بالنبضة لأنه بيتغيّر مع الراوتر.
const char *wifi_sandy_ip(void);

// تغيير الشبكة من التطبيق: كلمة سر غلط بتقطع الطريق الوحيد للرجوع، فبنجرّب الجديدة
// وإذا فشلت خلال WIFI_TRY_WINDOW_MS بنرجع للقديمة. بيانات التجربة بتنمسح عند الإقلاع.

#define WIFI_TRY_WINDOW_MS 25000

typedef enum {
    WIFI_SWITCH_OK = 0,        // الجديدة اشتغلت وانحفظت
    WIFI_SWITCH_FAILED,        // ما اتصلت — رجعنا للقديمة
    WIFI_SWITCH_BUSY,          // في تجربة شغّالة
    WIFI_SWITCH_BAD_ARGS,
    WIFI_SWITCH_BAD_PASSWORD,  // الراوتر رفض كلمة السر — رجعنا للقديمة
} wifi_switch_result_t;

// Router refused the password (not "no router"); cleared on a successful connect.
bool wifi_sandy_password_rejected(void);

// بتحجز لحدّ ما تخلص التجربة (٢٥ ثانية كحدّ أقصى). من مهمّة MQTT، مش من ISR.
wifi_switch_result_t wifi_sandy_switch(const char *ssid, const char *pass);

// يمسح كل إشي محفوظ ويعيد التشغيل (للبيع أو الإهداء).
void wifi_sandy_factory_reset(void);

// اسم الشبكة الحالية، للنبضة.
const char *wifi_sandy_ssid(void);

// الإشارة بـ dBm (سالبة، الأقرب للصفر أحسن)؛ تحت ‎-80 الصوت الحيّ ما بيمشي. صفر لو مش متصل.
int wifi_sandy_rssi(void);
