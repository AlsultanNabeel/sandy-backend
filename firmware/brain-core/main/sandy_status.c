// Health surface (contract in sandy_status.h). Non-blocking: called from Wi-Fi
// events and the websocket callback; drawing goes through face_set_banner().

#include "sandy_status.h"

#include <stdatomic.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "sandy_face.h"
#include "sandy_led.h"

static const char *TAG = "status";

static _Atomic int s_status = SANDY_ST_BOOTING;
static bool s_ready;

// One table, so a new status must define its face and its line.
typedef struct {
    sandy_mood_t       mood;
    sandy_led_state_t  led;
    const char      *banner;   // Latin, drawn on the face
    const char      *say;      // Arabic, logged with the banner
} status_face_t;

static const status_face_t TABLE[SANDY_ST_COUNT] = {
    [SANDY_ST_OK] = {
        MOOD_IDLE, LED_STATE_IDLE, "",
        "",
    },
    [SANDY_ST_BOOTING] = {
        MOOD_SLEEPY, LED_STATE_OFF, "STARTING",
        "لحظة، عم بصحى.",
    },
    [SANDY_ST_NO_WIFI] = {
        MOOD_WORRIED, LED_STATE_OFF, "NO WI-FI",
        "ما في واي فاي. شغّل الراوتر وأنا برجع لحالي.",
    },
    [SANDY_ST_NO_SERVER] = {
        MOOD_CONFUSED, LED_STATE_OFF, "NO INTERNET",
        "الواي فاي شغّال بس ما بوصل ع الإنترنت. ظبّط النت وارجع احكيني.",
    },
    [SANDY_ST_LINK_DROPPED] = {
        MOOD_DISAPPOINTED, LED_STATE_OFF, "LINK LOST",
        "النت قطع بنص الحكي. لما يرجع احكيني من جديد.",
    },
    [SANDY_ST_NET_SLOW] = {
        MOOD_THINKING, LED_STATE_LISTENING, "WEAK SIGNAL",
        "إشارة الواي فاي عندي ضعيفة وصوتي ما عم يلحق. قرّبني ع الراوتر.",
    },
    // الإشارة قوية هون، فما منوجّه المالك ع الراوتر.
    [SANDY_ST_LINK_STALL] = {
        MOOD_THINKING, LED_STATE_LISTENING, "LINK STALL",
        "الإشارة قوية بس الصوت متأخّر عن الوصول. لحظة وبرجع.",
    },
    [SANDY_ST_AUTH_FAILED] = {
        MOOD_ALERT, LED_STATE_OFF, "SETUP",
        "في مشكلة بالإعداد، الخادم ما قبلني. بدها مراجعة.",
    },
    [SANDY_ST_LOW_MEMORY] = {
        MOOD_ALERT, LED_STATE_OFF, "MEMORY",
        "ذاكرتي امتلت. رح أعيد تشغيل حالي.",
    },
    [SANDY_ST_WIFI_BAD_PASS] = {
        MOOD_CONFUSED, LED_STATE_OFF, "WI-FI PASSWORD",
        "الراوتر رفض كلمة السر. غيّرها من التطبيق أو اعمل إعداد من جديد.",
    },
};

sandy_status_t status_get(void)
{
    return (sandy_status_t)atomic_load(&s_status);
}

void status_init(void)
{
    s_ready = true;
    status_set(SANDY_ST_BOOTING);
}

void status_set(sandy_status_t st)
{
    if (st < 0 || st >= SANDY_ST_COUNT) return;

    // Same status as before: stay quiet (subsystems report on every retry).
    int prev = atomic_exchange(&s_status, (int)st);
    if (prev == (int)st) return;

    const status_face_t *f = &TABLE[st];

    if (st == SANDY_ST_OK) {
        ESP_LOGI(TAG, "recovered");
    } else {
        ESP_LOGW(TAG, "%s — %s", f->banner, f->say);
    }

    if (!s_ready) return;

    face_set_mood(f->mood);
    led_set_state(f->led);
    face_set_banner(f->banner);

    // Spoken line not played yet: the clips aren't in the partition table.
}
