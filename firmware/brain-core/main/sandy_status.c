// Health surface (contract in sandy_status.h). Non-blocking: called from Wi-Fi
// events and the websocket callback; drawing goes through face_set_banner().

#include "sandy_status.h"

#include <stdio.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"

#include "sandy_face.h"
#include "sandy_led.h"

static const char *TAG = "status";

// One status per part; the shown one is the most serious. A spinlock, not a mutex:
// Wi-Fi and websocket event handlers report here.
static int s_part[SANDY_PART_COUNT];
static int s_shown = SANDY_ST_OK;
static portMUX_TYPE s_lock = portMUX_INITIALIZER_UNLOCKED;
static bool s_ready;

// One table, so a new status must define its face, its line, its weight and its name.
typedef struct {
    sandy_mood_t       mood;
    sandy_led_state_t  led;
    const char      *banner;   // Latin, drawn on the face
    const char      *say;      // Arabic, logged with the banner
    int              rank;     // higher wins when two parts are not OK
    const char      *id;       // heartbeat name
} status_face_t;

static const status_face_t TABLE[SANDY_ST_COUNT] = {
    [SANDY_ST_OK] = {
        MOOD_IDLE, LED_STATE_IDLE, "",
        "",
        0, "ok",
    },
    [SANDY_ST_BOOTING] = {
        MOOD_SLEEPY, LED_STATE_OFF, "STARTING",
        "لحظة، عم بصحى.",
        1, "booting",
    },
    [SANDY_ST_NO_WIFI] = {
        MOOD_WORRIED, LED_STATE_OFF, "NO WI-FI",
        "ما في واي فاي. شغّل الراوتر وأنا برجع لحالي.",
        5, "no_wifi",
    },
    [SANDY_ST_NO_SERVER] = {
        MOOD_CONFUSED, LED_STATE_OFF, "NO INTERNET",
        "الواي فاي شغّال بس ما بوصل ع الإنترنت. ظبّط النت وارجع احكيني.",
        4, "no_server",
    },
    [SANDY_ST_LINK_DROPPED] = {
        MOOD_DISAPPOINTED, LED_STATE_OFF, "LINK LOST",
        "النت قطع بنص الحكي. لما يرجع احكيني من جديد.",
        3, "link_dropped",
    },
    [SANDY_ST_NET_SLOW] = {
        MOOD_THINKING, LED_STATE_LISTENING, "WEAK SIGNAL",
        "إشارة الواي فاي عندي ضعيفة وصوتي ما عم يلحق. قرّبني ع الراوتر.",
        2, "net_slow",
    },
    // الإشارة قوية هون، فما منوجّه المالك ع الراوتر.
    [SANDY_ST_LINK_STALL] = {
        MOOD_THINKING, LED_STATE_LISTENING, "LINK STALL",
        "الإشارة قوية بس الصوت متأخّر عن الوصول. لحظة وبرجع.",
        2, "link_stall",
    },
    [SANDY_ST_AUTH_FAILED] = {
        MOOD_ALERT, LED_STATE_OFF, "SETUP",
        "في مشكلة بالإعداد، الخادم ما قبلني. بدها مراجعة.",
        6, "auth_failed",
    },
    [SANDY_ST_LOW_MEMORY] = {
        MOOD_ALERT, LED_STATE_OFF, "MEMORY",
        "ذاكرتي امتلت. رح أعيد تشغيل حالي.",
        7, "low_memory",
    },
    [SANDY_ST_WIFI_BAD_PASS] = {
        MOOD_CONFUSED, LED_STATE_OFF, "WI-FI PASSWORD",
        "الراوتر رفض كلمة السر. غيّرها من التطبيق أو اعمل إعداد من جديد.",
        5, "wifi_bad_pass",
    },
    [SANDY_ST_SETTINGS_OFF] = {
        MOOD_CONFUSED, LED_STATE_OFF, "SETTINGS",
        "ما قدرت أفتح إعداداتي، فشغّالة بالافتراضي. أي تغيير ما رح ينحفظ.",
        3, "settings_off",
    },
    [SANDY_ST_VOICE_OFF] = {
        MOOD_ALERT, LED_STATE_OFF, "VOICE OFF",
        "ما بقدر أسمع ولا أحكي، الصوت عندي ما اشتغل. طفّيني وشغّلني، وإذا ضلّ هيك بدّي فحص.",
        7, "voice_off",
    },
    [SANDY_ST_NECK_OFF] = {
        MOOD_CONFUSED, LED_STATE_OFF, "NECK",
        "رقبتي ما اشتغلت، فما رح أتلفّت. باقي إشي شغّال.",
        3, "neck_off",
    },
    [SANDY_ST_SCREEN_OFF] = {
        MOOD_IDLE, LED_STATE_OFF, "SCREEN",
        "الشاشة ما اشتغلت. باقي إشي شغّال.",
        3, "screen_off",
    },
    [SANDY_ST_SAFE_MODE] = {
        MOOD_SLEEPY, LED_STATE_OFF, "SAFE MODE",
        "علّقت كذا مرّة ورا بعض، فقلعت بالوضع الآمن: شبكة وتحديث بس. بستنّى تحديث أو تطفيني وتشغّلني.",
        8, "safe_mode",
    },
};

static const char *const PART_NAME[SANDY_PART_COUNT] = {
    [SANDY_PART_SYSTEM] = "system",
    [SANDY_PART_NET]    = "net",
    [SANDY_PART_LINK]   = "link",
    [SANDY_PART_VOICE]  = "voice",
    [SANDY_PART_SETTINGS] = "settings",
    [SANDY_PART_NECK]   = "neck",
    [SANDY_PART_SCREEN] = "screen",
};

sandy_status_t status_get(void)
{
    portENTER_CRITICAL(&s_lock);
    int st = s_shown;
    portEXIT_CRITICAL(&s_lock);
    return (sandy_status_t)st;
}

sandy_status_t status_part_get(sandy_part_t part)
{
    if (part < 0 || part >= SANDY_PART_COUNT) return SANDY_ST_OK;
    portENTER_CRITICAL(&s_lock);
    int st = s_part[part];
    portEXIT_CRITICAL(&s_lock);
    return (sandy_status_t)st;
}

int status_faults_json(char *out, size_t cap)
{
    if (!out || cap == 0) return 0;
    int st[SANDY_PART_COUNT];
    portENTER_CRITICAL(&s_lock);
    for (int i = 0; i < SANDY_PART_COUNT; i++) st[i] = s_part[i];
    portEXIT_CRITICAL(&s_lock);

    int k = 0;
    out[0] = '\0';
    for (int i = 0; i < SANDY_PART_COUNT; i++) {
        if (st[i] == SANDY_ST_OK) continue;
        int n = snprintf(out + k, cap - k, "%s\"%s\":\"%s\"",
                         k ? "," : "", PART_NAME[i], TABLE[st[i]].id);
        if (n < 0 || n >= (int)(cap - k)) {
            out[k] = '\0';   // clipped: keep the members that fit whole
            break;
        }
        k += n;
    }
    return k;
}

static void show(int st)
{
    const status_face_t *f = &TABLE[st];
    face_set_mood(f->mood);
    led_set_state(f->led);
    face_set_banner(f->banner);

    // Spoken line not played yet: the clips aren't in the partition table.
}

void status_init(void)
{
    status_set(SANDY_PART_SYSTEM, SANDY_ST_BOOTING);
    // Faults reported before the face existed (the settings store opens first).
    s_ready = true;
    show(status_get());
}

void status_set(sandy_part_t part, sandy_status_t st)
{
    if (part < 0 || part >= SANDY_PART_COUNT || st < 0 || st >= SANDY_ST_COUNT) return;

    portENTER_CRITICAL(&s_lock);
    // Same status as before: stay quiet (subsystems report on every retry).
    if (s_part[part] == (int)st) {
        portEXIT_CRITICAL(&s_lock);
        return;
    }
    s_part[part] = (int)st;
    int worst = SANDY_ST_OK;
    for (int i = 0; i < SANDY_PART_COUNT; i++) {
        if (TABLE[s_part[i]].rank > TABLE[worst].rank) worst = s_part[i];
    }
    const int prev = s_shown;
    s_shown = worst;
    portEXIT_CRITICAL(&s_lock);

    if (st == SANDY_ST_OK) {
        ESP_LOGI(TAG, "%s recovered", PART_NAME[part]);
    } else {
        ESP_LOGW(TAG, "%s: %s — %s", PART_NAME[part], TABLE[st].banner, TABLE[st].say);
    }

    // A more serious fault elsewhere still stands: the face stays as it is.
    if (!s_ready || worst == prev) return;
    show(worst);
}
