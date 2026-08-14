// Sandy's health surface. See include/sandy_status.h for the contract.
//
// Everything here is deliberately cheap and non-blocking: it runs from whatever
// task noticed the problem — the Wi-Fi event handler, the websocket callback,
// the session manager — and none of those may stall. Drawing is handed to the
// LVGL task through face_set_banner(); the spoken line is queued for the
// speaker task rather than played inline.

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

// How each condition presents itself. Kept as one table so a new status cannot
// be added without deciding what she looks like and what she says — the old
// code spread this across three files and that is how states went unhandled.
typedef struct {
    sandy_mood_t       mood;
    sandy_led_state_t  led;
    const char      *banner;   // Latin, drawn on the face
    const char      *say;      // Arabic, spoken + logged
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
        MOOD_THINKING, LED_STATE_LISTENING, "SLOW NET",
        "النت بطيء وصوتي ما عم يوصل. قرّبني ع الراوتر.",
    },
    [SANDY_ST_AUTH_FAILED] = {
        MOOD_ALERT, LED_STATE_OFF, "SETUP",
        "في مشكلة بالإعداد، الخادم ما قبلني. بدها مراجعة.",
    },
    [SANDY_ST_LOW_MEMORY] = {
        MOOD_ALERT, LED_STATE_OFF, "MEMORY",
        "ذاكرتي امتلت. رح أعيد تشغيل حالي.",
    },
};

const char *status_text(sandy_status_t st)
{
    if (st < 0 || st >= SANDY_ST_COUNT) return "";
    return TABLE[st].say;
}

const char *status_banner(sandy_status_t st)
{
    if (st < 0 || st >= SANDY_ST_COUNT) return "";
    return TABLE[st].banner;
}

sandy_status_t status_get(void)
{
    return (sandy_status_t)atomic_load(&s_status);
}

bool status_is_degraded(void)
{
    return status_get() != SANDY_ST_OK;
}

void status_init(void)
{
    s_ready = true;
    status_set(SANDY_ST_BOOTING);
}

void status_set(sandy_status_t st)
{
    if (st < 0 || st >= SANDY_ST_COUNT) return;

    // Same condition as last time: say nothing. Subsystems retry in loops, and
    // a robot that repeats "no Wi-Fi" every two seconds is worse than one that
    // says it once and holds the face.
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

    // The spoken line is intentionally not played here yet: the clips are not
    // in the partition table. voice_say_status() is the hook — until it exists
    // the face and the banner already make every failure legible, which is the
    // part that was missing.
}
