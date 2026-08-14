#include "sandy_mqtt.h"
#include "sandy_types.h"
#include "sandy_servo.h"
#include "sandy_buzzer.h"
#include "sandy_motors.h"
#include "sandy_sensor.h"
#include "sandy_face.h"
#include "sandy_ota.h"
#include "sandy_led.h"
#include "sandy_audio_ctl.h"
#include "config.h"
#include "secrets.h"
#include "mqtt_client.h"
#include "esp_crt_bundle.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_system.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
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
    (void)val;
    spk_test_tone();
}

static void _handle_ns(const char *val) {
    if      (!strcmp(val, "off"))        ns_set_level(NS_OFF);
    else if (!strcmp(val, "mild"))       ns_set_level(NS_MILD);
    else if (!strcmp(val, "medium"))     ns_set_level(NS_MEDIUM);
    else if (!strcmp(val, "aggressive")) ns_set_level(NS_AGGRESSIVE);
    else ESP_LOGW(TAG, "unknown noise level: %s", val);
}

static void _handle_led(const char *val) {
    if      (!strcmp(val, "off"))       led_set_state(LED_STATE_OFF);
    else if (!strcmp(val, "idle"))      led_set_state(LED_STATE_IDLE);
    else if (!strcmp(val, "listening")) led_set_state(LED_STATE_LISTENING);
    else if (!strcmp(val, "talking"))   led_set_state(LED_STATE_TALKING);
    else ESP_LOGW(TAG, "unknown led state: %s", val);
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
            if (!ev->topic || !ev->data) break;
            char topic[64]  = {0};
            char val[256]   = {0};
            int  tlen = ev->topic_len  < 63  ? ev->topic_len  : 63;
            int  dlen = ev->data_len   < 255 ? ev->data_len   : 255;
            memcpy(topic, ev->topic, tlen);
            memcpy(val,   ev->data,  dlen);
            ESP_LOGD(TAG, "%s = %s", topic, val);

            const char *out = topic_suffix(topic);
            if (!out) {           // the wildcard can only deliver our own tree,
                break;            // but never trust that on a shared broker
            }
            // Our own status echoing back (retained, or a second robot's) must
            // not be parsed as a command.
            if (!strcmp(out, "status")) break;

            if      (!strcmp(out, "mood"))         _handle_mood(val);
            else if (!strcmp(out, "servo"))        _handle_servo(val);
            else if (!strcmp(out, "buzzer"))       _handle_buzzer(val);
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
            else if (!strcmp(out, "autonomous"))
                ESP_LOGI(TAG, "autonomous=%s (TODO)", val);
            else if (!strcmp(out, "ota"))
                ota_trigger(val);
            else
                ESP_LOGW(TAG, "unknown output: %s", out);
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
      "{\"id\":\"led\",\"kind\":\"pwm\"},"
      "{\"id\":\"buzzer\",\"kind\":\"buzzer\"},"
      "{\"id\":\"mic_l\",\"kind\":\"audio\"},"
      "{\"id\":\"mic_r\",\"kind\":\"audio\"},"
      "{\"id\":\"mic_l_gain\",\"kind\":\"audio\"},"
      "{\"id\":\"mic_r_gain\",\"kind\":\"audio\"},"
      "{\"id\":\"volume\",\"kind\":\"audio\"},"
      "{\"id\":\"speaker_test\",\"kind\":\"audio\"},"
      "{\"id\":\"noise\",\"kind\":\"audio\"}"
    "]";

void mqtt_publish_status(void) {
    if (!s_client) return;
    // 896, not 640: a full heartbeat with every output declared measures 621
    // bytes, and snprintf truncates silently — a heartbeat cut mid-JSON parses
    // as nothing and the robot's parts quietly stop registering. Leave room for
    // the next output someone adds.
    char buf[896];
    // mic_l / mic_r are live input levels, 0..100. They are in the heartbeat and
    // not on a topic of their own so a control screen gets meters by reading the
    // state it already polls — speak, watch which one moves, and you know which
    // mic is which without touching a wire.
    snprintf(buf, sizeof(buf),
        "{\"uptime\":%lld,\"heap\":%lu,\"mood\":%d,\"distance\":%lu,"
        "\"mic_l\":%d,\"mic_r\":%d,"
        "\"mic_l_gain\":%d,\"mic_r_gain\":%d,"
        "\"mic_l_muted\":%s,\"mic_r_muted\":%s,"
        "\"volume\":%d,\"noise\":%d,\"online\":true,"
        // Key names are the backend's, not ours: mqtt_ingest reads
        // "firmware_version", "capabilities" and "outputs" by those exact
        // spellings and silently ignores anything else. A heartbeat that looks
        // right and registers nothing is the failure mode to avoid here.
        "\"capabilities\":[\"servo\",\"pwm\",\"buzzer\",\"audio\"],"
        "\"firmware_version\":\"%s\",\"outputs\":%s}",
        esp_timer_get_time() / 1000000LL,
        (unsigned long)esp_get_free_heap_size(),
        (int)g_current_mood,
        (unsigned long)sensor_get_distance_cm(),
        mic_get_level(MIC_LEFT), mic_get_level(MIC_RIGHT),
        mic_get_gain(MIC_LEFT),  mic_get_gain(MIC_RIGHT),
        mic_is_muted(MIC_LEFT)  ? "true" : "false",
        mic_is_muted(MIC_RIGHT) ? "true" : "false",
        spk_get_volume(), (int)ns_get_level(),
        SANDY_FW_VERSION, OUTPUTS_JSON);
    esp_mqtt_client_publish(s_client, s_topic_status, buf, 0, 0, 0);
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

    esp_mqtt_client_config_t cfg = {
        .broker = {
            .address = { .uri = MQTT_BROKER_URI },
            // Real TLS via the built-in CA bundle (same as the voice WSS link).
            // skip_cert_common_name_check alone doesn't work here: esp-tls
            // refuses to connect with no verification source at all.
            .verification = { .crt_bundle_attach = esp_crt_bundle_attach },
        },
        .credentials = {
            .client_id  = MQTT_CLIENT_ID,
            .username   = MQTT_USER,
            .authentication = { .password = MQTT_PASS },
        },
        .network = { .reconnect_timeout_ms = MQTT_RECONNECT_MS },
    };

    s_client = esp_mqtt_client_init(&cfg);
    if (!s_client) return ESP_FAIL;

    esp_mqtt_client_register_event(s_client, ESP_EVENT_ANY_ID, _handler, NULL);
    esp_mqtt_client_start(s_client);

    xTaskCreate(_status_task, "mqtt_status", 3072, NULL, 4, NULL);
    ESP_LOGI(TAG, "started → %s", MQTT_BROKER_URI);
    return ESP_OK;
}
