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
#include "sandy_ir.h"
#include "sandy_voice.h"
#include "sandy_net_busy.h"
#include "config.h"
#include "sandy_identity.h"
#include "mqtt_client.h"
#include "esp_crt_bundle.h"
#include "nvs.h"          // بيانات دخول الوسيط الخاصة باللوح
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "esp_random.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/semphr.h"
#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include "sandy_health.h"

static const char *TAG = "mqtt";
static esp_mqtt_client_handle_t s_client = NULL;

// ─── Node identity ───
// Every robot answers on sandy/node/<node_id>/<output>. node_id comes from the
// box's pairing code with the SAME transform as the backend's
// node_store.code_to_node_id (lowercase, alphanumerics only). Keep them in lockstep.
static char s_node_id[33];
static char s_base[64];        // "sandy/node/<node_id>"
static char s_topic_status[80];

static void derive_node_id(void) {
    const char *src = identity()->pair_code;
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

// Suffix after "sandy/node/<id>/", or NULL if not ours (one wildcard serves every output).
static const char *topic_suffix(const char *topic) {
    size_t n = strlen(s_base);
    if (strncmp(topic, s_base, n) != 0 || topic[n] != '/') return NULL;
    return topic + n + 1;
}

// ─── Topic handlers ───

// A whole number and nothing else, within [lo, hi]. atoi turned "", "abc" or "5x" into
// 0 or 5: an empty volume muted her and an empty angle swung the neck to its end.
static bool parse_int(const char *s, int lo, int hi, int *out) {
    if (!s || !*s) return false;
    const char *p = s;
    if (*p == '-') p++;
    if (!*p) return false;
    long v = 0;
    for (; *p; p++) {
        if (*p < '0' || *p > '9') return false;
        v = v * 10 + (*p - '0');
        if (v > 1000000) return false;   // far past any range here
    }
    if (*s == '-') v = -v;
    if (v < lo || v > hi) return false;
    *out = (int)v;
    return true;
}

// The number after `"key":` in a small JSON payload, by the same rule.
static bool json_int(const char *json, const char *key, int lo, int hi, int *out) {
    const char *p = strstr(json, key);
    if (!p) return false;
    p += strlen(key);
    while (*p == ' ') p++;
    char num[12];
    size_t n = 0;
    while ((p[n] == '-' || (p[n] >= '0' && p[n] <= '9')) && n < sizeof(num) - 1) {
        num[n] = p[n];
        n++;
    }
    num[n] = '\0';
    return parse_int(num, lo, hi, out);
}

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
            face_set_mood_from_app(MOOD_MAP[i].mood);   // also sets g_current_mood
            return;
        }
    }
    ESP_LOGW(TAG, "unknown mood: %s", val);
}

static void _handle_servo(const char *val) {
    int angle;
    if (!parse_int(val, 0, 180, &angle)) { ESP_LOGW(TAG, "servo: not an angle: %.16s", val); return; }
    servo_move_to((uint8_t)angle);
}

// حركة = الجسم كله: رقبة + وش + نغمة + إضاءة.
// `MOOD_COUNT` / `MELODY_COUNT` / `LED_FX_COUNT` معناها «لا تغيّر هالجزء».
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

        if (s->mood < MOOD_COUNT) face_set_mood(s->mood);   // sets g_current_mood too
        if (s->melody < MELODY_COUNT) buzzer_play(s->melody);
        // `led_set_effect` بترجّع false وقت الجلسة الحيّة، فمؤشّر الخصوصية بيغلب.
        // Keep the current colour at mid speed (0 meant black).
        if (s->fx < LED_FX_COUNT) led_set_effect(s->fx, LED_RGB_KEEP, 5);

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

// Focus state (compact JSON from focus_store._focus_payload); hand-parsed, three fields.
static void _handle_focus(const char *val) {
    int phase = 0;   // 0 off, 1 focus, 2 break
    if      (strstr(val, "\"phase\":\"focus\"")) phase = 1;
    else if (strstr(val, "\"phase\":\"break\"")) phase = 2;
    int remaining = 0, total = 0;
    // A focus with broken numbers is refused; "off" needs none.
    if (phase != 0 &&
        (!json_int(val, "\"remaining_sec\":", 0, 24 * 3600, &remaining) ||
         !json_int(val, "\"total_sec\":", 0, 24 * 3600, &total))) {
        ESP_LOGW(TAG, "focus: bad numbers: %.60s", val);
        return;
    }
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

// ─── Audio handlers ───
// Plain payloads ("on", "off", a number), validated by the backend's device_store.command_payload.

static void _handle_mic_gain(sandy_mic_ch_t ch, const char *val) {
    int g;
    if (!parse_int(val, AUDIO_GAIN_MIN, AUDIO_GAIN_MAX, &g)) {
        ESP_LOGW(TAG, "mic gain: not a number in range: %.16s", val);
        return;
    }
    mic_set_gain(ch, g);
}

static void _handle_mic_mute(sandy_mic_ch_t ch, const char *val) {
    // "on" = mic on, so muted is the opposite.
    bool on = !strcmp(val, "on");
    mic_set_muted(ch, !on);
}

static void _handle_volume(const char *val) {
    int v;
    if (!parse_int(val, 0, 100, &v)) { ESP_LOGW(TAG, "volume: not 0..100: %.16s", val); return; }
    spk_set_volume(v);
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

// State names drive the privacy indicator (always wins); anything else is an
// effect, optionally "name:rrggbb:speed". See sandy_led.h.
static void _handle_led(const char *val) {
    if      (!strcmp(val, "idle"))      { led_set_state(LED_STATE_IDLE);      return; }
    else if (!strcmp(val, "listening")) { led_set_state(LED_STATE_LISTENING); return; }
    else if (!strcmp(val, "talking"))   { led_set_state(LED_STATE_TALKING);   return; }

    char name[16] = {0};
    uint32_t rgb = LED_RGB_KEEP;   // no colour keeps the current one
    int speed = 5;

    const char *c1 = strchr(val, ':');
    size_t nlen = c1 ? (size_t)(c1 - val) : strlen(val);
    if (nlen >= sizeof(name)) nlen = sizeof(name) - 1;
    memcpy(name, val, nlen);

    if (c1) {
        // Exactly six hex digits, or leave the colour alone.
        char *end = NULL;
        uint32_t v = (uint32_t)strtoul(c1 + 1, &end, 16);
        if (end == c1 + 7 && (*end == ':' || *end == '\0')) rgb = v;
        const char *c2 = strchr(c1 + 1, ':');
        if (c2 && !parse_int(c2 + 1, 1, 10, &speed)) {
            ESP_LOGW(TAG, "led: speed is not 1..10: %.16s", c2 + 1);
            return;
        }
    }

    sandy_led_fx_t fx = led_fx_from_name(name);
    if (fx == LED_FX_COUNT) { ESP_LOGW(TAG, "unknown led value: %s", val); return; }
    // "off" hands the light back to the indicator.
    if (fx == LED_FX_OFF) { led_set_state(LED_STATE_OFF); return; }
    led_set_effect(fx, rgb, speed);
}

// ── The display ──
// "text:..." shows a line, "dismiss" clears it, "img:<seq>:<total>:<base64>" is an image chunk.
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

// تغيير الشبكة. الحمولة: "<اسم>\n<كلمة السر>" (السطر الجديد الحرف الوحيد اللي ما بيكون جوّاهن).
// بيحجز لحدّ ٢٥ ثانية، فبيتنفّذ ع مهمّة لحاله: معالج MQTT ما لازم ينام.
typedef struct { char ssid[33]; char pass[65]; } wifi_req_t;

static void _wifi_switch_task(void *arg) {
    wifi_req_t *req = (wifi_req_t *)arg;
    wifi_switch_result_t r = wifi_sandy_switch(req->ssid, req->pass);
    free(req);
    // النتيجة بتبيّن بالنبضة الجاية (اسم الشبكة).
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

#if ENABLE_FACE
static void _handle_screen_size(const char *val) {
    screen_set_size(screen_size_from_name(val));
}

// Image chunk: seq 0 begins, seq total-1 ends; no separate begin/end commands.
static void _handle_screen_img(const char *val) {
    int seq = 0, total = 0, consumed = 0;
    if (sscanf(val, "%d:%d:%n", &seq, &total, &consumed) != 2 || consumed <= 0 ||
        seq < 0 || total <= 0 || seq >= total) {
        ESP_LOGW(TAG, "malformed image chunk header");
        return;
    }
    const char *b64 = val + consumed;
    size_t b64_len = strlen(b64);
    if (b64_len == 0) return;

    if (seq == 0 && !screen_image_begin(total)) return;

    // PSRAM: internal RAM is for voice.
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

// ─── Dispatch ───

// Dispatch a fully reassembled command, exactly once.
// One-shot commands: a retained copy is stale intent (a retained "erase" wiped
// the robot on every reconnect), so retained ones are ignored.
static bool _is_one_shot(const char *out) {
    return !strcmp(out, "factory_reset") || !strcmp(out, "wifi") ||
           !strcmp(out, "ota") || !strcmp(out, "ir") || !strcmp(out, "pair_code");
}

#if ENABLE_FACE
// ── Proof of presence ──
// Pairing shows six server-sent digits on her face; typing them proves you're in front of her.
// Five minutes, like the server's code, then the face returns.
static esp_timer_handle_t s_pair_timer;

static void _pair_code_expired(void *arg) {
    (void)arg;
    screen_dismiss();
}

static void _handle_pair_code(const char *val) {
    if (strlen(val) != 6) { ESP_LOGW(TAG, "pair code: not six digits"); return; }
    for (int i = 0; i < 6; i++) {
        if (val[i] < '0' || val[i] > '9') { ESP_LOGW(TAG, "pair code: not digits"); return; }
    }
    char text[64];
    // Two groups of three, easy to read and type.
    snprintf(text, sizeof(text), "رمز الربط\n\n%.3s  %.3s", val, val + 3);
    screen_show_text(text);
    buzzer_play(MELODY_NOTIFY);
    if (!s_pair_timer) {
        const esp_timer_create_args_t a = { .callback = _pair_code_expired, .name = "pair_code" };
        if (esp_timer_create(&a, &s_pair_timer) != ESP_OK) return;
    }
    esp_timer_stop(s_pair_timer);
    esp_timer_start_once(s_pair_timer, 5ULL * 60 * 1000 * 1000);
    ESP_LOGW(TAG, "showing a pairing code — someone is pairing this robot");
}
#endif

static void _dispatch(const char *out, const char *val, bool retained) {
    // مخارج الكاميرا وعقدة الغرفة ع نفس الشجرة؛ منتجاهلها بدل تحذير «مخرج مجهول».
    if (!strncmp(out, "cam/", 4) || !strncmp(out, "room/", 5)) return;
    if (retained && _is_one_shot(out)) {
        ESP_LOGW(TAG, "ignoring a retained %s — one-shot commands must be live", out);
        return;
    }
    // Safe mode: the body is off; only what can rescue her gets through.
    if (health_safe_mode() && strcmp(out, "wifi") && strcmp(out, "ota") &&
        strcmp(out, "factory_reset")) {
        ESP_LOGW(TAG, "safe mode — ignoring %s", out);
        return;
    }

    if      (!strcmp(out, "mood"))         _handle_mood(val);
    else if (!strcmp(out, "servo"))        _handle_servo(val);
    else if (!strcmp(out, "gesture"))      _handle_gesture(val);
    else if (!strcmp(out, "buzzer"))       _handle_buzzer(val);
    else if (!strcmp(out, "factory_reset")) {
        // كلمة وحدة بالضبط: أمر ما إله رجعة ما بيعتمد ع حارس واحد.
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
    else if (!strcmp(out, "screen"))       _handle_screen(val);
#if ENABLE_FACE
    else if (!strcmp(out, "pair_code"))    _handle_pair_code(val);
    else if (!strcmp(out, "screen_size"))  _handle_screen_size(val);
    else if (!strcmp(out, "screen_img"))   _handle_screen_img(val);
#endif
    else if (!strcmp(out, "autonomous"))
        ESP_LOGI(TAG, "autonomous=%s (TODO)", val);
    else if (!strcmp(out, "wifi"))         _handle_wifi(val);
#if ENABLE_IR
    // "learn" arms the receiver; anything else is a code to replay.
    else if (!strcmp(out, "ir"))           ir_handle(val);
#endif
    else if (!strcmp(out, "ota"))
        ota_check_now();   // never a URL from the message
    else
        ESP_LOGW(TAG, "unknown output: %s", out);
}

// ─── Reassembly ───
// Payloads over CONFIG_MQTT_BUFFER_SIZE (1 KB) arrive as several MQTT_EVENT_DATA
// events, with the topic only on the first. Reassembled in PSRAM rather than
// growing the internal-RAM MQTT buffer.
#define ASM_MAX (32 * 1024)     // an image chunk is 8 KB

static char  *s_asm;            // PSRAM, allocated per message
static size_t s_asm_len;
static size_t s_asm_total;
static char   s_asm_out[64];    // output name from the first event
static bool   s_asm_retained;   // and whether it was a retained message

static void _asm_reset(void) {
    if (s_asm) free(s_asm);
    s_asm = NULL;
    s_asm_len = s_asm_total = 0;
    s_asm_out[0] = '\0';
    s_asm_retained = false;
}

// ─── Reconnect: backoff with jitter ───
// 2 s doubling to a minute, ±25% jitter, so a fleet doesn't reconnect in lockstep.
#define MQTT_BACKOFF_MIN_MS  2000
#define MQTT_BACKOFF_MAX_MS  60000

static uint32_t           s_backoff_ms;
static esp_timer_handle_t s_reconnect_timer;

static void _reconnect_cb(void *arg) {
    (void)arg;
    if (s_client) esp_mqtt_client_reconnect(s_client);
}

static void _schedule_reconnect(void) {
    s_backoff_ms = s_backoff_ms ? s_backoff_ms * 2 : MQTT_BACKOFF_MIN_MS;
    if (s_backoff_ms > MQTT_BACKOFF_MAX_MS) s_backoff_ms = MQTT_BACKOFF_MAX_MS;
    uint32_t quarter = s_backoff_ms / 4;
    uint32_t wait = s_backoff_ms - quarter + (quarter ? esp_random() % (2 * quarter) : 0);
    ESP_LOGW(TAG, "disconnected — retrying in %lu ms", (unsigned long)wait);
    if (s_reconnect_timer) {
        esp_timer_stop(s_reconnect_timer);
        esp_timer_start_once(s_reconnect_timer, (uint64_t)wait * 1000);
    }
}

// ─── MQTT event handler ───

static void _handler(void *arg, esp_event_base_t base, int32_t id, void *data) {
    esp_mqtt_event_handle_t ev = (esp_mqtt_event_handle_t)data;
    switch ((esp_mqtt_event_id_t)id) {
        case MQTT_EVENT_CONNECTED: {
            ESP_LOGI(TAG, "connected");
            s_backoff_ms = 0;
            // One wildcard subscription: new outputs only need a dispatch case.
            char sub[80];
            snprintf(sub, sizeof(sub), "%s/#", s_base);
            if (esp_mqtt_client_subscribe(s_client, sub, 1) < 0) {
                // Connected but unsubscribed obeys nothing: start over.
                ESP_LOGE(TAG, "subscribe to %s could not be sent — reconnecting", sub);
                esp_mqtt_client_disconnect(s_client);
                break;
            }
            ESP_LOGI(TAG, "subscribing to %s", sub);
            // Clears the retained "offline" will.
            esp_mqtt_client_publish(s_client, s_topic_status, "{\"online\":true}", 0, 1, 1);
            mqtt_publish_status();   // announce what this robot can do, at once
            // No chime: it played on every reconnect.
            break;
        }

        case MQTT_EVENT_SUBSCRIBED:
            // SUBACK 0x80 = refused (no permission on this tree).
            if (ev->data_len > 0 && (uint8_t)ev->data[0] == 0x80) {
                ESP_LOGE(TAG, "the broker refused our subscription — check this board's "
                              "credential permissions on %s/#", s_base);
            } else {
                ESP_LOGI(TAG, "subscribed");
            }
            break;

        case MQTT_EVENT_DISCONNECTED:
            _schedule_reconnect();
            break;

        case MQTT_EVENT_DATA: {
            if (!ev->data) break;

            // ── Continuation: no topic, use the name kept from the first event ──
            if (ev->current_data_offset > 0) {
                if (!s_asm) break;                 // not one of ours; ignore
                if (ev->current_data_offset != s_asm_len) {
                    // Out of order or lost: drop the whole message.
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
                _dispatch(s_asm_out, s_asm, s_asm_retained);
                _asm_reset();
                break;
            }

            // ── First (or only) event of a message ──
            if (!ev->topic) break;
            _asm_reset();                          // drop any abandoned message

            char topic[64] = {0};
            int  tlen = ev->topic_len < 63 ? ev->topic_len : 63;
            memcpy(topic, ev->topic, tlen);

            const char *out = topic_suffix(topic);
            if (!out) {           // the wildcard only delivers our own tree,
                break;            // but never trust that on a shared broker
            }
            // Our own status echoing back is not a command.
            if (!strcmp(out, "status")) break;

            // فرع الكاميرا (نفس معرّف الوحدة، واشتراك `#`): أي موضوع فيه شرطة مش إلنا، بصمت.
            if (strchr(out, '/')) break;

            // Whole and short: stays on the stack. 512 fits a 255-byte line plus "text:".
            if ((size_t)ev->total_data_len == (size_t)ev->data_len
                && ev->data_len < 512) {
                char val[512] = {0};
                memcpy(val, ev->data, ev->data_len);
                // Never log the Wi-Fi password (dev builds mirror the log off the board).
                ESP_LOGD(TAG, "%s = %s", topic, strcmp(out, "wifi") ? val : "<redacted>");
                _dispatch(out, val, ev->retain);
                break;
            }

            // Long: reassemble in PSRAM.
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
            s_asm_retained = ev->retain;

            if (s_asm_len >= s_asm_total) {        // single oversized event
                s_asm[s_asm_len] = '\0';
                _dispatch(s_asm_out, s_asm, s_asm_retained);
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

// ─── Status publisher ───

// Parts this robot declares, so the backend provisions them. Each `id` is a topic
// suffix handled above; `kind` must be in node_store.KNOWN_CAPABILITIES or the
// backend drops it.
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
      "{\"id\":\"screen\",\"kind\":\"pwm\"},"
#if ENABLE_IR
      "{\"id\":\"ir\",\"kind\":\"ir\"},"
#endif
      "{\"id\":\"screen_size\",\"kind\":\"pwm\"}"
    "]";

// Created in mqtt_sandy_start before either user exists (lazy init raced).
static SemaphoreHandle_t s_status_lock;

// SSIDs can hold quotes/backslashes; worst case doubles 32 bytes.
static void json_escape(const char *in, char *out, size_t cap) {
    size_t k = 0;
    for (; in && *in && k + 2 < cap; in++) {
        unsigned char c = (unsigned char)*in;
        if (c < 0x20) continue;                 // control bytes: drop, don't escape
        if (c == '"' || c == '\\') out[k++] = '\\';
        out[k++] = (char)c;
    }
    out[k] = '\0';
}

void mqtt_publish_status(void) {
    if (!s_client || !s_status_lock) return;
    // Not on the 3 KB task stack (it overflowed): PSRAM, once, under s_status_lock since
    // the status timer and connect handler both publish. Worst case ~1500 bytes: past
    // CONFIG_MQTT_BUFFER_SIZE, which the client sends in pieces.
    enum { BUF_CAP = 2048, HEALTH_CAP = 640 };
    static char *buf, *health;
    if (xSemaphoreTake(s_status_lock, pdMS_TO_TICKS(200)) != pdTRUE) return;
    if (!buf) buf = heap_caps_malloc(BUF_CAP + HEALTH_CAP, MALLOC_CAP_SPIRAM);
    if (!buf) {
        xSemaphoreGive(s_status_lock);
        ESP_LOGE(TAG, "no memory for the heartbeat");
        return;
    }
    health = buf + BUF_CAP;
    static char ssid[2 * 32 + 1];   // under the lock, like buf
    json_escape(wifi_sandy_ssid(), ssid, sizeof(ssid));
    if (health_json(health, HEALTH_CAP) < 0) {
        ESP_LOGW(TAG, "health members do not fit — heartbeat sent without them");
        snprintf(health, HEALTH_CAP, "\"safe\":%s", health_safe_mode() ? "true" : "false");
    }
    int n =
    // Live mic levels 0..100, in the heartbeat so the app's meters need no extra topic.
        snprintf(buf, BUF_CAP,
        // ما في distance: الحسّاس مش مركّب (ENABLE_SENSOR=0).
        "{\"uptime\":%lld,\"heap\":%lu,\"mood\":%d,"
        "\"mic_l\":%d,\"mic_r\":%d,"
        "\"mic_l_gain\":%d,\"mic_r_gain\":%d,"
        "\"mic_l_muted\":%s,\"mic_r_muted\":%s,"
        "\"volume\":%d,\"online\":true,"
        // قوّة الإشارة: لتشخيص «النت بطيء».
        "\"rssi\":%d,"
        // Exact backend key names (mqtt_ingest ignores anything else).
        "\"capabilities\":[\"servo\",\"pwm\",\"buzzer\",\"audio\"],"
        "\"ip\":\"%s\",\"ssid\":\"%s\",\"board\":\"" SANDY_BOARD_ID "\","
        "\"firmware_version\":\"%s\",%s,\"outputs\":%s}",
        esp_timer_get_time() / 1000000LL,
        (unsigned long)esp_get_free_heap_size(),
        (int)g_current_mood,
        mic_get_level(MIC_LEFT), mic_get_level(MIC_RIGHT),
        mic_get_gain(MIC_LEFT),  mic_get_gain(MIC_RIGHT),
        mic_is_muted(MIC_LEFT)  ? "true" : "false",
        mic_is_muted(MIC_RIGHT) ? "true" : "false",
        spk_get_volume(), wifi_sandy_rssi(),
        wifi_sandy_ip(), ssid,
        SANDY_FW_VERSION, health, OUTPUTS_JSON);
    // Clipped JSON gets dropped whole by the server.
    if (n < 0 || n >= BUF_CAP) {
        ESP_LOGE(TAG, "heartbeat is %d bytes, buffer %u — not sent", n, (unsigned)BUF_CAP);
    } else {
        esp_mqtt_client_publish(s_client, s_topic_status, buf, n, 0, 0);
    }
    xSemaphoreGive(s_status_lock);
}

// Publish under sandy/node/<id>/…, never a global tree shared across customers.
bool mqtt_publish_node(const char *suffix, const char *payload) {
    if (!s_client || !suffix || !payload) return false;
    if (s_base[0] == '\0') {
        ESP_LOGW(TAG, "no node id yet — dropping %s", suffix);
        return false;
    }
    char topic[96];
    snprintf(topic, sizeof(topic), "%s/%s", s_base, suffix);
    int id = esp_mqtt_client_publish(s_client, topic, payload, 0, 0, 0);
    // Truncated: IR codes would flood the 8 KB remote log buffer.
    ESP_LOGI(TAG, "publish %s = %.60s%s (%s)", topic, payload,
             strlen(payload) > 60 ? "…" : "", id < 0 ? "FAIL" : "ok");
    return id >= 0;
}

bool mqtt_publish_room(const char *out, const char *payload) {
    if (!out) return false;
    char suffix[64];
    snprintf(suffix, sizeof(suffix), "room/%s", out);
    return mqtt_publish_node(suffix, payload);
}

static void _apply_pending_credentials(void);

static void _status_task(void *arg) {
    health_watch();
    for (;;) {
        health_feed();
        vTaskDelay(pdMS_TO_TICKS(MQTT_STATUS_INTERVAL_MS));
        health_feed();
        // The client's lock is held through a reconnect's TLS handshake: a wait on purpose.
        health_unwatch();
        _apply_pending_credentials();
        mqtt_publish_status();
        health_watch();
    }
}

// ─── Broker credentials ───
// كل لوح بياخد مفتاح وسيط خاص فيه: `creds_load` بتقرا المحفوظ وإلا المكتوب بالكود،
// و`mqtt_sandy_set_credentials` بتحفظ المفتاح اللي بيجي من مصافحة الصوت.

#define CREDS_NS "sandy_mqtt"

static char s_user[65], s_pass[129];
static volatile bool s_creds_pending;

// نسخة كاملة من الإعداد: `esp_mqtt_set_config` بترجّع أي حقل ناقص للافتراضي.
static esp_mqtt_client_config_t s_cfg;

static void creds_load(void) {
    snprintf(s_user, sizeof(s_user), "%s", identity()->mqtt_user);
    snprintf(s_pass, sizeof(s_pass), "%s", identity()->mqtt_pass);

    nvs_handle_t h;
    if (nvs_open(CREDS_NS, NVS_READONLY, &h) != ESP_OK) {
        ESP_LOGI(TAG, "broker credentials: shared (compiled in)");
        return;
    }
    size_t n = sizeof(s_user);
    if (nvs_get_str(h, "user", s_user, &n) != ESP_OK)
        snprintf(s_user, sizeof(s_user), "%s", identity()->mqtt_user);
    n = sizeof(s_pass);
    if (nvs_get_str(h, "pass", s_pass, &n) != ESP_OK)
        snprintf(s_pass, sizeof(s_pass), "%s", identity()->mqtt_pass);
    nvs_close(h);

    ESP_LOGI(TAG, "broker credentials: %s",
             strcmp(s_user, identity()->mqtt_user) ? "per-device (stored)" : "shared (compiled in)");
}

bool mqtt_sandy_set_credentials(const char *user, const char *pass) {
    if (!user || !pass || !*user || !*pass) return false;

    // نفس المفتاح؟ ما منكتب (توفيرًا للذاكرة الوامضة).
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

    // منطبّقها بهالتشغيلة، بس مش هلّق: إعادة الاتصال فوق مصافحة الصوت بتخلّص الرام
    // الداخلية. مهمّة النبضة بتطبّقها لمّا الشبكة تفضى.
    s_creds_pending = true;
    return true;
}

static void _apply_pending_credentials(void) {
    if (!s_creds_pending || !s_client) return;
    if (voice_is_connected() || net_owner() != NET_OWNER_NONE) return;   // later
    s_creds_pending = false;
    // مؤشّرات أصلًا جوّا s_cfg، بس منكتبهن صراحة.
    s_cfg.credentials.username = s_user;
    s_cfg.credentials.authentication.password = s_pass;
    if (esp_mqtt_set_config(s_client, &s_cfg) == ESP_OK) {
        // Disconnect, not reconnect: the library ignores reconnect on a live link, and a
        // clean DISCONNECT doesn't fire the "offline" will.
        esp_mqtt_client_disconnect(s_client);
        ESP_LOGI(TAG, "reconnecting with the new credential");
    } else {
        ESP_LOGW(TAG, "could not apply the new credential live — next boot will");
    }
}

// ─── Init ───

esp_err_t mqtt_sandy_start(void) {
    derive_node_id();
    if (s_node_id[0] == '\0') {
        // No pairing code, no topics: refuse loudly.
        ESP_LOGE(TAG, "SANDY_PAIR_CODE is empty or has no alphanumerics — "
                      "flash once by cable with it in secrets.h, or provision the factory partition");
        return ESP_ERR_INVALID_STATE;
    }

    // بيانات الدخول: المحفوظة أول، وإلا المكتوبة بالكود.
    creds_load();

    // معرّف العميل خاص باللوح: الوسيط بيفصل عميلين بنفس المعرّف.
    static char s_client_id[48];
    snprintf(s_client_id, sizeof(s_client_id), "sandy-brain-%s", s_node_id);

    s_cfg = (esp_mqtt_client_config_t){
        .broker = {
            .address = { .uri = identity()->mqtt_uri },
            // Real TLS via the CA bundle; esp-tls refuses with no verification source.
            .verification = { .crt_bundle_attach = esp_crt_bundle_attach },
        },
        .credentials = {
            .client_id  = s_client_id,
            .username   = s_user,
            .authentication = { .password = s_pass },
        },
        // Our backoff, not the library's fixed interval.
        .network = { .reconnect_timeout_ms = MQTT_RECONNECT_MS,
                     .disable_auto_reconnect = true },
        // وصيّة «offline» محفوظة، عشان التطبيق يعرف فورًا.
        .session = {
            .last_will = {
                .topic  = s_topic_status,
                .msg    = "{\"online\":false}",
                .qos    = 1,
                .retain = 1,
            },
        },
    };

    s_status_lock = xSemaphoreCreateMutex();
    if (!s_status_lock) return ESP_ERR_NO_MEM;

    const esp_timer_create_args_t rt = { .callback = _reconnect_cb, .name = "mqtt_retry" };
    if (esp_timer_create(&rt, &s_reconnect_timer) != ESP_OK) return ESP_ERR_NO_MEM;

    s_client = esp_mqtt_client_init(&s_cfg);
    if (!s_client) return ESP_FAIL;

    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, _handler, NULL);
    esp_mqtt_client_start(s_client);

    // Stack in PSRAM (no flash access), to spare internal RAM for voice TLS.
    if (xTaskCreateWithCaps(_status_task, "mqtt_status", 3072, NULL, 4, NULL,
                            MALLOC_CAP_SPIRAM) != pdPASS) {
        xTaskCreate(_status_task, "mqtt_status", 3072, NULL, 4, NULL);
    }
    ESP_LOGI(TAG, "started → %s", identity()->mqtt_uri);
    return ESP_OK;
}
