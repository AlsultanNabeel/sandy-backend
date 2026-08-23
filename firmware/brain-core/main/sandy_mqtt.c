#include "sandy_mqtt.h"
#include "sandy_types.h"
#include "sandy_servo.h"
#include "sandy_buzzer.h"
#include "sandy_motors.h"
#include "sandy_sensor.h"
#include "sandy_face.h"
#include "sandy_ota.h"
#include "sandy_led.h"
#include "sandy_screen.h"
#include "mbedtls/base64.h"
#include "esp_heap_caps.h"
#include "sandy_audio_ctl.h"
#include "sandy_wifi.h"
#include "config.h"
#include "secrets.h"
#include "mqtt_client.h"
#include "esp_crt_bundle.h"
#include "nvs.h"          // بيانات دخول الوسيط الخاصة باللوح، لو انحفظت
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>

static const char *TAG = "mqtt";
static esp_mqtt_client_handle_t s_client = NULL;

// ─── Node identity ────────────────────────────────────────────────────────────
//
// Every robot answers on its own topics: sandy/node/<node_id>/<output>.
//
// It used to be the bare strings sandy/cmd/mood, sandy/cmd/servo and so on —
// which works exactly as long as there is one robot in the world. Two on the
// same broker and each one obeys the other's owner. That is not a bug you find
// in testing; it is a bug the second customer finds.
//
// node_id is derived from the pairing code printed on the box, with the SAME
// transform the backend uses (node_store.code_to_node_id): lowercase, keep
// alphanumerics only. Deriving it rather than provisioning it means the board
// knows its own topics on first boot, before it has ever been paired with an
// account — no handshake, no server round-trip, nothing to go wrong at the
// customer's house.
//
// Keep this in lockstep with node_store.code_to_node_id. If one side changes the
// transform, the robot goes quiet and nothing says why.
static char s_node_id[33];
static char s_base[64];        // "sandy/node/<node_id>"
static char s_topic_status[80];

static void derive_node_id(void) {
    const char *src = SANDY_PAIR_CODE;
    size_t j = 0;
    for (size_t i = 0; src[i] && j < sizeof(s_node_id) - 1; i++) {
        char c = src[i];
        if (c >= 'A' && c <= 'Z') c = (char)(c - 'A' + 'a');
        if ((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9')) s_node_id[j++] = c;
    }
    s_node_id[j] = '\0';
    snprintf(s_base, sizeof(s_base), "sandy/node/%s", s_node_id);
    snprintf(s_topic_status, sizeof(s_topic_status), "%s/status", s_base);
    ESP_LOGI(TAG, "node id = %s", s_node_id);
}

// The part of an incoming topic after "sandy/node/<id>/", or NULL if the topic
// is not ours. Comparing the prefix rather than the whole string is what lets
// one wildcard subscription serve every output.
static const char *topic_suffix(const char *topic) {
    size_t n = strlen(s_base);
    if (strncmp(topic, s_base, n) != 0 || topic[n] != '/') return NULL;
    return topic + n + 1;
}

// ─── Topic handlers ───────────────────────────────────────────────────────────

static const struct { const char *name; sandy_mood_t mood; } MOOD_MAP[] = {
    {"idle",        MOOD_IDLE},       {"happy",       MOOD_HAPPY},
    {"curious",     MOOD_CURIOUS},    {"sad",         MOOD_SAD},
    {"alert",       MOOD_ALERT},      {"surprised",   MOOD_SURPRISED},
    {"big_happy",   MOOD_BIG_HAPPY},  {"focused",     MOOD_FOCUSED},
    {"bored",       MOOD_BORED},      {"excited",     MOOD_EXCITED},
    {"love",        MOOD_LOVE},       {"angry",       MOOD_ANGRY},
    {"confused",    MOOD_CONFUSED},   {"thinking",    MOOD_THINKING},
    {"sleepy",      MOOD_SLEEPY},     {"shy",         MOOD_SHY},
    {"proud",       MOOD_PROUD},      {"worried",     MOOD_WORRIED},
    {"playful",     MOOD_PLAYFUL},    {"calm",        MOOD_CALM},
    {"grumpy",      MOOD_GRUMPY},     {"hopeful",     MOOD_HOPEFUL},
    {"grateful",    MOOD_GRATEFUL},   {"disappointed",MOOD_DISAPPOINTED},
    {"silly",       MOOD_SILLY},
};

static void _handle_mood(const char *val) {
    for (size_t i = 0; i < sizeof(MOOD_MAP)/sizeof(MOOD_MAP[0]); i++) {
        if (!strcmp(val, MOOD_MAP[i].name)) {
            g_current_mood = MOOD_MAP[i].mood;
            face_set_mood(MOOD_MAP[i].mood);
            return;
        }
    }
    ESP_LOGW(TAG, "unknown mood: %s", val);
}

static void _handle_servo(const char *val) {
    int angle = atoi(val);
    if (angle >= 0 && angle <= 180) servo_set_angle((uint8_t)angle);
}

// حركة = الجسم كله، مش الرقبة لحالها.
//
// كانت الحركة بتنادي المحرّك وبس. يعني «ارقصي» بتهزّ رقبتها بوش محايد وبسكوت
// وبإضاءة زرقا عادية — والنتيجة بتبيّن عطل مش رقصة، مع إنّ كل قطعة كانت شغّالة
// تمامًا لحالها.
//
// وكل اللي كان ناقص هالجدول. التعبير موجود، والنغمة موجودة، والتأثير موجود —
// تلاتتهن مبرمجين ومختبَرين ومستنيين حدا يناديهن سوا.
//
// `MOOD_COUNT` معناها «لا تلمس الوش»، و`MELODY_COUNT` «لا تعزف»، و`LED_FX_COUNT`
// «لا تغيّر الإضاءة» — لأنّ «بصّي ع الشمال» مش لازم يعزف نغمة، والحركة الصامتة
// خيار مقصود مش نسيان.
typedef struct {
    const char      *name;
    sandy_gesture_t  g;
    sandy_mood_t     mood;
    sandy_melody_t   melody;
    sandy_led_fx_t   fx;
} gesture_scene_t;

static const gesture_scene_t GESTURE_MAP[] = {
    // الاسم        الحركة               الوش              النغمة              الإضاءة
    {"nod",        GESTURE_NOD,        MOOD_HAPPY,       MELODY_YES,        LED_FX_COUNT},
    {"shake",      GESTURE_SHAKE,      MOOD_CONFUSED,    MELODY_NO,         LED_FX_COUNT},
    {"tilt",       GESTURE_TILT,       MOOD_CURIOUS,     MELODY_CURIOUS,    LED_FX_COUNT},
    {"scan",       GESTURE_SCAN,       MOOD_ALERT,       MELODY_COUNT,      LED_FX_PULSE},
    {"dance",      GESTURE_DANCE,      MOOD_PLAYFUL,     MELODY_CELEBRATE,  LED_FX_PARTY},
    {"wake",       GESTURE_WAKE,       MOOD_HAPPY,       MELODY_HELLO,      LED_FX_SUNRISE},
    {"sleep",      GESTURE_SLEEP,      MOOD_SLEEPY,      MELODY_BYE,        LED_FX_BREATHE},
    {"look_left",  GESTURE_LOOK_LEFT,  MOOD_COUNT,       MELODY_COUNT,      LED_FX_COUNT},
    {"look_right", GESTURE_LOOK_RIGHT, MOOD_COUNT,       MELODY_COUNT,      LED_FX_COUNT},
    {"center",     GESTURE_CENTER,     MOOD_IDLE,        MELODY_COUNT,      LED_FX_COUNT},
};

static void _handle_gesture(const char *val) {
    for (size_t i = 0; i < sizeof(GESTURE_MAP)/sizeof(GESTURE_MAP[0]); i++) {
        const gesture_scene_t *s = &GESTURE_MAP[i];
        if (strcmp(val, s->name)) continue;

        if (s->mood < MOOD_COUNT) {
            g_current_mood = s->mood;
            face_set_mood(s->mood);
        }
        if (s->melody < MELODY_COUNT) buzzer_play(s->melody);
        // الإضاءة آخر إشي، و`led_set_effect` بترجّع false وقت الجلسة الحيّة —
        // مؤشّر الخصوصية بيغلب. يعني «ارقصي» وهي بتسمعك بترقص وبتغنّي، وبيضلّ
        // الضوّ يقول إنّ المايك شغّال. وهاد صحيح: الرقصة ما بتلغي التحذير.
        if (s->fx < LED_FX_COUNT) led_set_effect(s->fx, 0, 0);

        servo_gesture(s->g);
        return;
    }
    ESP_LOGW(TAG, "unknown gesture: %s", val);
}

static void _handle_buzzer(const char *val) {
    if      (!strcmp(val, "boot"))    buzzer_play(MELODY_BOOT);
    else if (!strcmp(val, "happy"))   buzzer_play(MELODY_HAPPY);
    else if (!strcmp(val, "curious")) buzzer_play(MELODY_CURIOUS);
    else if (!strcmp(val, "sad"))     buzzer_play(MELODY_SAD);
    else if (!strcmp(val, "alert"))   buzzer_play(MELODY_ALERT);
    else if (!strcmp(val, "error"))   buzzer_play(MELODY_ERROR);
    else if (!strcmp(val, "focus_start")) buzzer_play(MELODY_FOCUS_START);
    else if (!strcmp(val, "focus_break")) buzzer_play(MELODY_FOCUS_BREAK);
    else if (!strcmp(val, "focus_end"))   buzzer_play(MELODY_FOCUS_END);
    else if (!strcmp(val, "hello"))       buzzer_play(MELODY_HELLO);
    else if (!strcmp(val, "bye"))         buzzer_play(MELODY_BYE);
    else if (!strcmp(val, "yes"))         buzzer_play(MELODY_YES);
    else if (!strcmp(val, "no"))          buzzer_play(MELODY_NO);
    else if (!strcmp(val, "thinking"))    buzzer_play(MELODY_THINKING);
    else if (!strcmp(val, "celebrate"))   buzzer_play(MELODY_CELEBRATE);
    else if (!strcmp(val, "notify"))      buzzer_play(MELODY_NOTIFY);
    else if (!strcmp(val, "lowbatt"))     buzzer_play(MELODY_LOWBATT);
    else ESP_LOGW(TAG, "unknown melody: %s", val);
}

// Live focus-session state (compact JSON from focus_store._focus_payload).
// Hand-parsed — no cJSON dependency for three fields.
static void _handle_focus(const char *val) {
    int phase = 0;   // 0 off, 1 focus, 2 break
    if      (strstr(val, "\"phase\":\"focus\"")) phase = 1;
    else if (strstr(val, "\"phase\":\"break\"")) phase = 2;
    int remaining = 0, total = 0;
    const char *p;
    if ((p = strstr(val, "\"remaining_sec\":"))) remaining = atoi(p + 16);
    if ((p = strstr(val, "\"total_sec\":")))     total     = atoi(p + 12);
    face_set_focus(phase, remaining, total);
}

static void _handle_base(const char *val) {
    if      (!strcmp(val, "forward"))  motors_command(MOTOR_FORWARD,  0);
    else if (!strcmp(val, "backward")) motors_command(MOTOR_BACKWARD, 0);
    else if (!strcmp(val, "left"))     motors_command(MOTOR_LEFT,     0);
    else if (!strcmp(val, "right"))    motors_command(MOTOR_RIGHT,    0);
    else if (!strcmp(val, "stop"))     motors_stop();
    else ESP_LOGW(TAG, "unknown base cmd: %s", val);
}

// ─── Audio handlers ───────────────────────────────────────────────────────────
//
// Deliberately plain payloads — "on", "off", a bare number — because the backend
// validates them in device_store.command_payload and sends the payload string
// straight through. Parsing JSON here would mean two validators disagreeing.

static void _handle_mic_gain(sandy_mic_ch_t ch, const char *val) {
    mic_set_gain(ch, atoi(val));
}

static void _handle_mic_mute(sandy_mic_ch_t ch, const char *val) {
    // "on" means the mic is ON, so muted is the opposite. Reading it the other
    // way round is the obvious mistake here and it would be silent.
    bool on = !strcmp(val, "on");
    mic_set_muted(ch, !on);
}

static void _handle_volume(const char *val) {
    spk_set_volume(atoi(val));
}

static void _handle_speaker_test(const char *val) {
    if      (!strcmp(val, "beep"))  spk_play(SPK_BEEP);
    else if (!strcmp(val, "chime")) spk_play(SPK_CHIME);
    else if (!strcmp(val, "alert")) spk_play(SPK_ALERT);
    else if (!strcmp(val, "sweep")) spk_play(SPK_SWEEP);
    else if (!strcmp(val, "soft"))  spk_play(SPK_SOFT);
    else if (!strcmp(val, "happy")) spk_play(SPK_HAPPY);
    else spk_play(SPK_BEEP);   // مجهول = الفحص العادي، مش صمت محيّر
}

static void _handle_ns(const char *val) {
    if      (!strcmp(val, "off"))        ns_set_level(NS_OFF);
    else if (!strcmp(val, "mild"))       ns_set_level(NS_MILD);
    else if (!strcmp(val, "medium"))     ns_set_level(NS_MEDIUM);
    else if (!strcmp(val, "aggressive")) ns_set_level(NS_AGGRESSIVE);
    else ESP_LOGW(TAG, "unknown noise level: %s", val);
}

// The light has two layers and this routes between them. The four state names
// are the privacy indicator and always win; everything else is an effect, which
// the LED module refuses while a session is live. See sandy_led.h.
//
// An effect may carry a colour and a speed: "breathe:ff0044:7". Both optional,
// because "breathe" alone should work.
static void _handle_led(const char *val) {
    if      (!strcmp(val, "idle"))      { led_set_state(LED_STATE_IDLE);      return; }
    else if (!strcmp(val, "listening")) { led_set_state(LED_STATE_LISTENING); return; }
    else if (!strcmp(val, "talking"))   { led_set_state(LED_STATE_TALKING);   return; }

    char name[16] = {0};
    uint32_t rgb = 0x00A0FF;
    int speed = 5;

    const char *c1 = strchr(val, ':');
    size_t nlen = c1 ? (size_t)(c1 - val) : strlen(val);
    if (nlen >= sizeof(name)) nlen = sizeof(name) - 1;
    memcpy(name, val, nlen);

    if (c1) {
        rgb = (uint32_t)strtoul(c1 + 1, NULL, 16);
        const char *c2 = strchr(c1 + 1, ':');
        if (c2) speed = atoi(c2 + 1);
    }

    sandy_led_fx_t fx = led_fx_from_name(name);
    if (fx == LED_FX_COUNT) { ESP_LOGW(TAG, "unknown led value: %s", val); return; }
    // "off" is the one name in both layers: it means darkness AND hands the
    // light back to the indicator, so it goes through led_set_state.
    if (fx == LED_FX_OFF) { led_set_state(LED_STATE_OFF); return; }
    led_set_effect(fx, rgb, speed);
}

// ── The display ──────────────────────────────────────────────────────────────
//
// "text:..." puts a line up, "dismiss" takes it down. Anything else is an image
// chunk, which arrives as "img:<seq>:<total>:<base64>" — see sandy_screen.h for
// why a picture is chunked and pre-converted rather than decoded here.
static void _handle_screen(const char *val) {
#if ENABLE_FACE
    if (!strncmp(val, "text:", 5))     { screen_show_text(val + 5); return; }
    if (!strcmp(val, "dismiss"))       { screen_dismiss();          return; }
    if (!strcmp(val, "clear"))         { screen_dismiss();          return; }
    ESP_LOGW(TAG, "unknown screen command: %.24s", val);
#else
    (void)val;
#endif
}

#if ENABLE_FACE
// One piece of a picture: "img:<seq>:<total>:<base64>".
//
// seq 0 starts the transfer and seq total-1 finishes it, so the app sends one
// kind of message and the board needs no separate begin/end commands to get out
// of step with.
// تغيير الشبكة. الحمولة: "<اسم>\n<كلمة السر>"
//
// سطر جديد فاصلًا مش فاصلة: أسماء الشبكات وكلمات السر فيها فواصل ونقطتين
// وكل علامة ترقيم بتخطر ع بالك، والسطر الجديد هو الحرف الوحيد اللي ما بيقدر
// يكون جوّاهن.
//
// **هالنداء بيحجز لحدّ خمسة وعشرين ثانية** — بيجرّب الشبكة وبيرجع للقديمة لو
// فشلت. عشان هيك بيتنفّذ ع مهمّة لحاله: معالج أحداث MQTT ما بيجوز ينام، وإذا
// نام بتتكدّس الرسائل ويسقط الاتصال.
typedef struct { char ssid[33]; char pass[65]; } wifi_req_t;

static void _wifi_switch_task(void *arg) {
    wifi_req_t *req = (wifi_req_t *)arg;
    wifi_switch_result_t r = wifi_sandy_switch(req->ssid, req->pass);
    free(req);
    // النتيجة بتوصل بالنبضة الجاية — لو الشبكة الجديدة اشتغلت، النبضة بتطلع
    // منها وباسمها. ولو فشلت، بتطلع من القديمة، والتطبيق بيشوف إنه الاسم ما
    // تغيّر. مش لازم رسالة خاصة: الحقيقة موجودة بالنبضة أصلًا.
    ESP_LOGI(TAG, "wifi switch result=%d", (int)r);
    vTaskDelete(NULL);
}

static void _handle_wifi(const char *val) {
    const char *nl = strchr(val, '\n');
    if (!nl) { ESP_LOGW(TAG, "wifi: no password line"); return; }

    wifi_req_t *req = calloc(1, sizeof(wifi_req_t));
    if (!req) return;
    size_t slen = (size_t)(nl - val);
    if (slen >= sizeof(req->ssid)) { free(req); return; }
    memcpy(req->ssid, val, slen);
    snprintf(req->pass, sizeof(req->pass), "%s", nl + 1);

    if (xTaskCreate(_wifi_switch_task, "wifi_switch", 4096, req, 5, NULL) != pdPASS) {
        free(req);
    }
}

static void _handle_screen_size(const char *val) {
    screen_set_size(screen_size_from_name(val));
}

static void _handle_screen_img(const char *val) {
    int seq = 0, total = 0, consumed = 0;
    if (sscanf(val, "%d:%d:%n", &seq, &total, &consumed) != 2 || consumed <= 0) {
        ESP_LOGW(TAG, "malformed image chunk header");
        return;
    }
    const char *b64 = val + consumed;
    size_t b64_len = strlen(b64);
    if (b64_len == 0) return;

    if (seq == 0 && !screen_image_begin(total)) return;

    // Decoded into PSRAM: a chunk is a few kilobytes and internal RAM is what
    // the voice session needs.
    size_t out_len = 0;
    mbedtls_base64_decode(NULL, 0, &out_len, (const unsigned char *)b64, b64_len);
    if (out_len == 0 || out_len > 16384) {
        ESP_LOGW(TAG, "image chunk %d: bad size %u", seq, (unsigned)out_len);
        return;
    }
    uint8_t *raw = heap_caps_malloc(out_len, MALLOC_CAP_SPIRAM);
    if (!raw) { ESP_LOGW(TAG, "no PSRAM for image chunk"); return; }

    if (mbedtls_base64_decode(raw, out_len, &out_len,
                              (const unsigned char *)b64, b64_len) == 0) {
        screen_image_chunk(seq, raw, out_len);
        if (seq == total - 1) screen_image_end();
    } else {
        ESP_LOGW(TAG, "image chunk %d: base64 decode failed", seq);
    }
    free(raw);
}
#endif

// ─── Dispatch ─────────────────────────────────────────────────────────────────

// One command, fully assembled. Separated from the event handler because a
// large payload arrives in pieces and must be dispatched exactly once, when the
// last piece lands — not once per piece.
static void _dispatch(const char *out, const char *val) {
    if      (!strcmp(out, "mood"))         _handle_mood(val);
    else if (!strcmp(out, "servo"))        _handle_servo(val);
    else if (!strcmp(out, "gesture"))      _handle_gesture(val);
    else if (!strcmp(out, "buzzer"))       _handle_buzzer(val);
    else if (!strcmp(out, "factory_reset")) {
        // كلمة وحدة بالضبط. الموضوع بينشر عليه الخادم بس، بس أمر ما إله رجعة
        // ما بيستاهل يعتمد ع حارس واحد — أي حمولة تانية بتنتجاهل.
        if (!strcmp(val, "erase")) {
            ESP_LOGW(TAG, "factory reset requested — erasing");
            wifi_sandy_factory_reset();   // بتمسح وبتعيد التشغيل، ما بترجع
        }
    }
    else if (!strcmp(out, "base"))         _handle_base(val);
    else if (!strcmp(out, "focus"))        _handle_focus(val);
    else if (!strcmp(out, "led"))          _handle_led(val);
    else if (!strcmp(out, "mic_l"))        _handle_mic_mute(MIC_LEFT,  val);
    else if (!strcmp(out, "mic_r"))        _handle_mic_mute(MIC_RIGHT, val);
    else if (!strcmp(out, "mic_l_gain"))   _handle_mic_gain(MIC_LEFT,  val);
    else if (!strcmp(out, "mic_r_gain"))   _handle_mic_gain(MIC_RIGHT, val);
    else if (!strcmp(out, "volume"))       _handle_volume(val);
    else if (!strcmp(out, "speaker_test")) _handle_speaker_test(val);
    else if (!strcmp(out, "noise"))        _handle_ns(val);
    else if (!strcmp(out, "screen"))       _handle_screen(val);
#if ENABLE_FACE
    else if (!strcmp(out, "screen_size"))  _handle_screen_size(val);
    else if (!strcmp(out, "screen_img"))   _handle_screen_img(val);
#endif
    else if (!strcmp(out, "autonomous"))
        ESP_LOGI(TAG, "autonomous=%s (TODO)", val);
    else if (!strcmp(out, "wifi"))         _handle_wifi(val);
    else if (!strcmp(out, "ota"))
        ota_trigger(val);
    else
        ESP_LOGW(TAG, "unknown output: %s", out);
}

// ─── Reassembly ───────────────────────────────────────────────────────────────
//
// A payload larger than CONFIG_MQTT_BUFFER_SIZE (1 KB here) does not arrive as
// one event. esp-mqtt delivers it as a run of MQTT_EVENT_DATA events, each
// carrying `data_len` bytes at `current_data_offset` of a `total_data_len`
// whole — and the topic is present **only on the first one**.
//
// This code did not know that. It copied 255 bytes out of whichever event it
// saw and dispatched. For every short command that was right, and so it looked
// right for months. For a picture it was catastrophic: a 6 KB chunk becomes 8 KB
// of base64, arrives in eight events, and about 190 bytes of the first one got
// decoded — three per cent of a chunk. The board reported the picture as
// incomplete because it genuinely was, and said so correctly every time.
//
// Raising the MQTT buffer instead would have been the smaller diff and the
// worse fix: that buffer is internal RAM, the one memory that is actually
// scarce, and it would have to be sized for the largest message anyone ever
// sends. Reassembling into PSRAM costs no internal RAM and has no ceiling worth
// worrying about.
#define ASM_MAX (32 * 1024)     // an image chunk is 8 KB; this is room to spare

static char  *s_asm;            // PSRAM, allocated per message
static size_t s_asm_len;
static size_t s_asm_total;
static char   s_asm_out[64];    // the output name, kept from the first event

static void _asm_reset(void) {
    if (s_asm) free(s_asm);
    s_asm = NULL;
    s_asm_len = s_asm_total = 0;
    s_asm_out[0] = '\0';
}

// ─── MQTT event handler ───────────────────────────────────────────────────────

static void _handler(void *arg, esp_event_base_t base, int32_t id, void *data) {
    esp_mqtt_event_handle_t ev = (esp_mqtt_event_handle_t)data;
    switch ((esp_mqtt_event_id_t)id) {
        case MQTT_EVENT_CONNECTED: {
            ESP_LOGI(TAG, "connected");
            // One wildcard instead of a subscription per output: adding a new
            // control becomes a case in the dispatch below, with nothing to
            // remember to subscribe to. Forgetting that line is how a handler
            // gets written and never fires.
            char sub[80];
            snprintf(sub, sizeof(sub), "%s/#", s_base);
            esp_mqtt_client_subscribe(s_client, sub, 1);
            ESP_LOGI(TAG, "subscribed to %s", sub);
            mqtt_publish_status();   // announce what this robot can do, at once
            buzzer_play(MELODY_BOOT);
            break;
        }

        case MQTT_EVENT_DISCONNECTED:
            ESP_LOGW(TAG, "disconnected — will auto-reconnect");
            break;

        case MQTT_EVENT_DATA: {
            if (!ev->data) break;

            // ── A continuation of a message already in progress ──────────────
            // No topic on these events, so the output name is the one kept from
            // the first.
            if (ev->current_data_offset > 0) {
                if (!s_asm) break;                 // not one of ours; ignore
                if (ev->current_data_offset != s_asm_len) {
                    // Out of order or a piece lost. Half a picture is worse than
                    // none, so abandon the whole message rather than draw it.
                    ESP_LOGW(TAG, "%s: piece out of order (%d, expected %u)",
                             s_asm_out, (int)ev->current_data_offset,
                             (unsigned)s_asm_len);
                    _asm_reset();
                    break;
                }
                if (s_asm_len + ev->data_len > s_asm_total) { _asm_reset(); break; }
                memcpy(s_asm + s_asm_len, ev->data, ev->data_len);
                s_asm_len += ev->data_len;
                if (s_asm_len < s_asm_total) break;      // still more to come

                s_asm[s_asm_len] = '\0';
                _dispatch(s_asm_out, s_asm);
                _asm_reset();
                break;
            }

            // ── The first (or only) event of a message ───────────────────────
            if (!ev->topic) break;
            _asm_reset();                          // drop any abandoned message

            char topic[64] = {0};
            int  tlen = ev->topic_len < 63 ? ev->topic_len : 63;
            memcpy(topic, ev->topic, tlen);

            const char *out = topic_suffix(topic);
            if (!out) {           // the wildcard can only deliver our own tree,
                break;            // but never trust that on a shared broker
            }
            // Our own status echoing back (retained, or a second robot's) must
            // not be parsed as a command.
            if (!strcmp(out, "status")) break;

            // فرع الكاميرا. اللوحين بيشاركوا معرّف الوحدة — الكاميرا جزء من
            // ساندي مش صندوق تاني — واشتراكنا `#` بيوصّلنا كل شي تحته. أي
            // موضوع فيه شرطة مش إلنا، فبنتجاهله بصمت بدل ما نحذّر منه: تحذير
            // بيتكرر كل خمس ثواني بيعلّمك تتخطّى التحذيرات.
            if (strchr(out, '/')) break;

            // Arrived whole and short: the common case, and it stays on the
            // stack. 512 rather than 256 because a full-length display line is
            // 255 bytes *plus* the "text:" prefix, and the old buffer clipped
            // the last few letters off a long Arabic sentence.
            if ((size_t)ev->total_data_len == (size_t)ev->data_len
                && ev->data_len < 512) {
                char val[512] = {0};
                memcpy(val, ev->data, ev->data_len);
                ESP_LOGD(TAG, "%s = %s", topic, val);
                _dispatch(out, val);
                break;
            }

            // Long: reassemble in PSRAM across the events still to come.
            if (ev->total_data_len <= 0 || ev->total_data_len > ASM_MAX) {
                ESP_LOGW(TAG, "%s: %d bytes is more than we accept",
                         out, (int)ev->total_data_len);
                break;
            }
            s_asm = heap_caps_malloc(ev->total_data_len + 1, MALLOC_CAP_SPIRAM);
            if (!s_asm) { ESP_LOGW(TAG, "no PSRAM to assemble %s", out); break; }
            memcpy(s_asm, ev->data, ev->data_len);
            s_asm_len   = ev->data_len;
            s_asm_total = ev->total_data_len;
            snprintf(s_asm_out, sizeof(s_asm_out), "%s", out);

            if (s_asm_len >= s_asm_total) {        // single oversized event
                s_asm[s_asm_len] = '\0';
                _dispatch(s_asm_out, s_asm);
                _asm_reset();
            }
            break;
        }

        case MQTT_EVENT_ERROR:
            ESP_LOGE(TAG, "error type=%d",
                     ev->error_handle ? ev->error_handle->error_type : -1);
            break;

        default: break;
    }
}

// ─── Status publisher ─────────────────────────────────────────────────────────

// The parts this robot ships with, declared by the robot itself.
//
// The buyer should open the app and find her face, her neck and her mics already
// there — not an empty list and a manual "add device" form for hardware that came
// in the box. But hardcoding that list in the backend would be a lie the moment a
// board ships without a servo, and it breaks the registry's own rule that devices
// are data rather than code.
//
// So the hardware declares itself and the backend provisions what it hears. Each
// entry's `id` is the topic suffix above, so a declared output is by construction
// an output that has a handler.
//
// `kind` must be one of node_store.KNOWN_CAPABILITIES — relay, pwm, servo,
// buzzer, ir, audio — or the backend drops the entry on validation. That set is
// the contract; widen it there first, not here.
static const char *OUTPUTS_JSON =
    "["
      "{\"id\":\"mood\",\"kind\":\"pwm\"},"
      "{\"id\":\"servo\",\"kind\":\"servo\"},"
      "{\"id\":\"gesture\",\"kind\":\"servo\"},"
      "{\"id\":\"led\",\"kind\":\"pwm\"},"
      "{\"id\":\"buzzer\",\"kind\":\"buzzer\"},"
      "{\"id\":\"mic_l\",\"kind\":\"audio\"},"
      "{\"id\":\"mic_r\",\"kind\":\"audio\"},"
      "{\"id\":\"mic_l_gain\",\"kind\":\"audio\"},"
      "{\"id\":\"mic_r_gain\",\"kind\":\"audio\"},"
      "{\"id\":\"volume\",\"kind\":\"audio\"},"
      "{\"id\":\"speaker_test\",\"kind\":\"audio\"},"
      "{\"id\":\"noise\",\"kind\":\"audio\"},"
      "{\"id\":\"screen\",\"kind\":\"pwm\"},"
      "{\"id\":\"screen_size\",\"kind\":\"pwm\"}"
    "]";

void mqtt_publish_status(void) {
    if (!s_client) return;
    // static, not on the stack.
    //
    // This buffer grew from 256 to 896 bytes when the heartbeat started carrying
    // the outputs, the mic levels and the address — and the task that calls this
    // has a 3 KB stack. 896 bytes of it, plus snprintf's own frame, overflowed
    // it and panicked the board mid-conversation. FreeRTOS caught it and said so
    // exactly, which is the only reason this took minutes to find rather than
    // days.
    //
    // A static buffer costs no stack at all. Two tasks can reach this — the
    // status timer and the MQTT event handler on connect — so the mutex below is
    // what makes sharing it safe. Without it, a connect landing mid-publish
    // would interleave two JSON documents into one and the backend would parse
    // neither.
    static char buf[896];
    static SemaphoreHandle_t buf_lock;
    if (!buf_lock) buf_lock = xSemaphoreCreateMutex();
    if (buf_lock && xSemaphoreTake(buf_lock, pdMS_TO_TICKS(200)) != pdTRUE) return;
    // mic_l / mic_r are live input levels, 0..100. They are in the heartbeat and
    // not on a topic of their own so a control screen gets meters by reading the
    // state it already polls — speak, watch which one moves, and you know which
    // mic is which without touching a wire.
    snprintf(buf, sizeof(buf),
        // ما في distance: الحسّاس ملغي ومش مركّب (ENABLE_SENSOR=0). حقل بيرسل
        // صفر للأبد بيوهم إنه في قياس.
        "{\"uptime\":%lld,\"heap\":%lu,\"mood\":%d,"
        "\"mic_l\":%d,\"mic_r\":%d,"
        "\"mic_l_gain\":%d,\"mic_r_gain\":%d,"
        "\"mic_l_muted\":%s,\"mic_r_muted\":%s,"
        "\"volume\":%d,\"noise\":%d,\"online\":true,"
        // Key names are the backend's, not ours: mqtt_ingest reads
        // "firmware_version", "capabilities" and "outputs" by those exact
        // spellings and silently ignores anything else. A heartbeat that looks
        // right and registers nothing is the failure mode to avoid here.
        "\"capabilities\":[\"servo\",\"pwm\",\"buzzer\",\"audio\"],"
        "\"ip\":\"%s\",\"ssid\":\"%s\",\"board\":\"" SANDY_BOARD_ID "\","
        "\"firmware_version\":\"%s\",\"outputs\":%s}",
        esp_timer_get_time() / 1000000LL,
        (unsigned long)esp_get_free_heap_size(),
        (int)g_current_mood,
        mic_get_level(MIC_LEFT), mic_get_level(MIC_RIGHT),
        mic_get_gain(MIC_LEFT),  mic_get_gain(MIC_RIGHT),
        mic_is_muted(MIC_LEFT)  ? "true" : "false",
        mic_is_muted(MIC_RIGHT) ? "true" : "false",
        spk_get_volume(), (int)ns_get_level(),
        wifi_sandy_ip(), wifi_sandy_ssid(),
        SANDY_FW_VERSION, OUTPUTS_JSON);
    esp_mqtt_client_publish(s_client, s_topic_status, buf, 0, 0, 0);
    if (buf_lock) xSemaphoreGive(buf_lock);
}

// Raw publish for local command words (room node lives on the same broker).
bool mqtt_publish_room(const char *topic, const char *payload) {
    if (!s_client || !topic || !payload) return false;
    int id = esp_mqtt_client_publish(s_client, topic, payload, 0, 0, 0);
    ESP_LOGI(TAG, "publish %s = %s (%s)", topic, payload, id < 0 ? "FAIL" : "ok");
    return id >= 0;
}

static void _status_task(void *arg) {
    for (;;) {
        vTaskDelay(pdMS_TO_TICKS(MQTT_STATUS_INTERVAL_MS));
        mqtt_publish_status();
    }
}

// ─── Broker credentials ───────────────────────────────────────────────────────
//
// **كل لوح بينباع فيه نفس المستخدم ونفس كلمة السرّ، مكتوبين بالكود.** يعني أي
// زبون بيقدر يشترك بمواضيع أي زبون تاني: صوت بيته، صور كاميرته، أوامره. ولوح
// واحد بينفتح بينكشف معه كل الزباين — وما في طريقة تسحب مفتاحًا واحدًا بدون حرق
// كل الأجهزة اللي بالسوق.
//
// الحلّ نصّين: اللوح يقدر ياخد مفتاحه ويحفظه، والخادم يعطيه ياه. هدول الاثنين
// هون: `creds_load` بتقرا المحفوظ وبتقع ع المكتوب بالكود، و
// `mqtt_sandy_set_credentials` بتستقبل المفتاح الخاص من مصافحة الصوت وبتحفظه.

#define CREDS_NS "sandy_mqtt"

static char s_user[65], s_pass[129];

// إعداد العميل بيضل محفوظ لأنّ `esp_mqtt_set_config` **بترجّع أي حقل مش معبّى
// لقيمته الافتراضية** — مش بتعدّل اللي بتعطيها ياه وبس. تمرير إعداد فيه المفتاح
// لحاله كان بيمسح عنوان الوسيط والتحقّق المشفّر ومعرّف العميل، ويرجع اللوح
// يحاول يتصل بلا مكان يروح عليه. فمنعدّل نسخة كاملة ومنمرّرها كلها.
static esp_mqtt_client_config_t s_cfg;

static void creds_load(void) {
    snprintf(s_user, sizeof(s_user), "%s", MQTT_USER);
    snprintf(s_pass, sizeof(s_pass), "%s", MQTT_PASS);

    nvs_handle_t h;
    if (nvs_open(CREDS_NS, NVS_READONLY, &h) != ESP_OK) {
        ESP_LOGI(TAG, "broker credentials: shared (compiled in)");
        return;
    }
    size_t n = sizeof(s_user);
    if (nvs_get_str(h, "user", s_user, &n) != ESP_OK)
        snprintf(s_user, sizeof(s_user), "%s", MQTT_USER);
    n = sizeof(s_pass);
    if (nvs_get_str(h, "pass", s_pass, &n) != ESP_OK)
        snprintf(s_pass, sizeof(s_pass), "%s", MQTT_PASS);
    nvs_close(h);

    ESP_LOGI(TAG, "broker credentials: %s",
             strcmp(s_user, MQTT_USER) ? "per-device (stored)" : "shared (compiled in)");
}

bool mqtt_sandy_set_credentials(const char *user, const char *pass) {
    if (!user || !pass || !*user || !*pass) return false;

    // نفس اللي عنا؟ ما منكتب. المصافحة بتصير كل جلسة صوت، وكتابة بكل مصافحة
    // بتآكل الذاكرة الوامضة مقابل لا شي.
    if (!strcmp(user, s_user) && !strcmp(pass, s_pass)) return false;

    nvs_handle_t h;
    if (nvs_open(CREDS_NS, NVS_READWRITE, &h) != ESP_OK) {
        ESP_LOGE(TAG, "cannot open %s to store the broker credential", CREDS_NS);
        return false;
    }
    esp_err_t e1 = nvs_set_str(h, "user", user);
    esp_err_t e2 = nvs_set_str(h, "pass", pass);
    esp_err_t e3 = nvs_commit(h);
    nvs_close(h);
    if (e1 != ESP_OK || e2 != ESP_OK || e3 != ESP_OK) {
        ESP_LOGE(TAG, "storing the broker credential failed");
        return false;
    }

    snprintf(s_user, sizeof(s_user), "%s", user);
    snprintf(s_pass, sizeof(s_pass), "%s", pass);
    ESP_LOGW(TAG, "stored this board's own broker credential (user=%s)", s_user);

    // بنطبّقها هلق مش ع الإقلاع الجاي: لوح حافظ مفتاحه وشغّال ع المشترك بيضل
    // ثغرة مفتوحة لحدّ ما حدا يطفّيه — وما حدا بيطفّي روبوت.
    if (s_client) {
        // s_user/s_pass مؤشّراتهن أصلًا جوّا s_cfg، بس منكتبهن صراحة عشان
        // السطر يضل صحيح لو انتغيّر شكل البنية.
        s_cfg.credentials.username = s_user;
        s_cfg.credentials.authentication.password = s_pass;
        if (esp_mqtt_set_config(s_client, &s_cfg) == ESP_OK) {
            esp_mqtt_client_reconnect(s_client);
            ESP_LOGI(TAG, "reconnecting with the new credential");
        } else {
            ESP_LOGW(TAG, "could not apply the new credential live — next boot will");
        }
    }
    return true;
}

// ─── Init ─────────────────────────────────────────────────────────────────────

esp_err_t mqtt_sandy_start(void) {
    derive_node_id();
    if (s_node_id[0] == '\0') {
        // No usable pairing code means no topics, and every command would land
        // on "sandy/node//…" where nothing is listening. Refuse loudly instead
        // of running as a robot that silently ignores the app.
        ESP_LOGE(TAG, "SANDY_PAIR_CODE is empty or has no alphanumerics — "
                      "set it in secrets.h to the code printed on the box");
        return ESP_ERR_INVALID_STATE;
    }

    // بيانات دخول الوسيط — من الذاكرة أول، ومن الكود لو ما في. التفصيل فوق.
    creds_load();

    // **معرّف العميل لازم يكون خاص باللوح.**
    //
    // كان مكتوب ثابت بالكود، ونفس القيمة بتنحرق ع كل لوح. والوسيط بيسمح
    // بمعرّف واحد بس لكل عميل: أول ما لوحين يتصلوا بنفس المعرّف بيفصل كل واحد
    // التاني، لفّة بلا نهاية. وهاد بيصير حتى لو كل واحد بمفتاح خاص فيه — يعني
    // إصدار المفاتيح لحاله ما بينفع بدون هالسطر.
    static char s_client_id[48];
    snprintf(s_client_id, sizeof(s_client_id), "sandy-brain-%s", s_node_id);

    s_cfg = (esp_mqtt_client_config_t){
        .broker = {
            .address = { .uri = MQTT_BROKER_URI },
            // Real TLS via the built-in CA bundle (same as the voice WSS link).
            // skip_cert_common_name_check alone doesn't work here: esp-tls
            // refuses to connect with no verification source at all.
            .verification = { .crt_bundle_attach = esp_crt_bundle_attach },
        },
        .credentials = {
            .client_id  = s_client_id,
            .username   = s_user,
            .authentication = { .password = s_pass },
        },
        .network = { .reconnect_timeout_ms = MQTT_RECONNECT_MS },
    };

    s_client = esp_mqtt_client_init(&s_cfg);
    if (!s_client) return ESP_FAIL;

    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, _handler, NULL);
    esp_mqtt_client_start(s_client);

    xTaskCreate(_status_task, "mqtt_status", 3072, NULL, 4, NULL);
    ESP_LOGI(TAG, "started → %s", MQTT_BROKER_URI);
    return ESP_OK;
}
