#include "sandy_servo.h"
#include "sandy_nvs.h"
#include "config.h"
#include "driver/ledc.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include <math.h>
#include <stdlib.h>

static const char *TAG = "servo";

#define ARRAY_LEN_S(a) (sizeof(a) / sizeof((a)[0]))
static uint8_t s_angle = SERVO_DEFAULT_POS;

// Map angle [0-180] to LEDC duty for 14-bit timer at 50Hz (period = 20000us)
static uint32_t _angle_to_duty(uint8_t angle) {
    uint32_t pw_us = SERVO_MIN_US +
        (uint32_t)angle * (SERVO_MAX_US - SERVO_MIN_US) / 180;
    return (pw_us * ((1 << 14) - 1)) / 20000;
}

esp_err_t servo_init(void) {
    ledc_timer_config_t timer = {
        .speed_mode      = LEDC_LOW_SPEED_MODE,
        .duty_resolution = SERVO_RESOLUTION,
        .timer_num       = LEDC_TIMER_SERVO,
        .freq_hz         = SERVO_FREQ_HZ,
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer));

    ledc_channel_config_t ch = {
        .gpio_num   = PIN_SERVO,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel    = LEDC_CH_SERVO,
        .timer_sel  = LEDC_TIMER_SERVO,
        .duty       = _angle_to_duty(SERVO_DEFAULT_POS),
        .hpoint     = 0,
        .flags      = { .output_invert = 0 },
    };
    ESP_ERROR_CHECK(ledc_channel_config(&ch));

    uint8_t saved = SERVO_DEFAULT_POS;
    if (nvs_load_servo_angle(&saved) == ESP_OK) {
        ESP_LOGI(TAG, "restored angle=%d from NVS", saved);
    }
    servo_set_angle(saved);
    return ESP_OK;
}

void servo_set_angle(uint8_t angle) {
    if (angle < SERVO_SAFE_MIN) angle = SERVO_SAFE_MIN;
    if (angle > SERVO_SAFE_MAX) angle = SERVO_SAFE_MAX;
    if (angle == s_angle) return;

    // Sine ease in-out: smooth motion between s_angle → angle
    int from = s_angle, to = angle;
    int steps = abs(to - from);
    for (int i = 1; i <= steps; i++) {
        float t     = (float)i / (float)steps;
        float eased = (1.0f - cosf(t * (float)M_PI)) * 0.5f;
        uint8_t pos = (uint8_t)(from + (to - from) * eased);
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CH_SERVO, _angle_to_duty(pos));
        ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CH_SERVO);
        vTaskDelay(pdMS_TO_TICKS(20));   // 50Hz
    }

    s_angle = angle;
    // Queued, not written. The neck moves on every wake word and on every step
    // of a gesture; writing flash on each one is what has been resetting the
    // board (see sandy_nvs.h). What lands is where the head came to rest.
    nvs_save_deferred("sandy", "servo_pos", NVS_VAL_U8, angle);
    ESP_LOGI(TAG, "angle=%d", angle);
}

uint8_t servo_get_angle(void) { return s_angle; }

// ── Gestures ─────────────────────────────────────────────────────────────────
// Contract and reasoning: include/sandy_servo.h

typedef struct { int8_t offset; uint16_t hold_ms; } step_t;

// Offsets from wherever her head already is, not absolute angles. A nod that
// snapped to 90 first would yank her head straight before agreeing with you,
// and the gesture would read as a correction rather than a reply.
static const step_t G_NOD[]        = {{-18,140},{0,120},{-18,140},{0,160}};
static const step_t G_SHAKE[]      = {{-22,130},{22,130},{-16,120},{16,120},{0,150}};
static const step_t G_TILT[]       = {{-26,600},{0,220}};
static const step_t G_SCAN[]       = {{-55,700},{55,1200},{0,600}};
static const step_t G_DANCE[]      = {{-20,180},{20,180},{-20,180},{20,180},
                                      {-12,160},{12,160},{0,200}};
// A startle then a settle: bigger and quicker than a nod, so hearing her name
// looks like being noticed rather than agreed with.
static const step_t G_WAKE[]       = {{-14,90},{8,110},{0,140}};
static const step_t G_SLEEP[]      = {{10,400},{20,700}};
static const step_t G_LOOK_LEFT[]  = {{-45,400}};
static const step_t G_LOOK_RIGHT[] = {{45,400}};

typedef struct { const step_t *steps; size_t count; bool absolute_center; } gesture_def_t;

static const gesture_def_t GESTURES[GESTURE_COUNT] = {
    [GESTURE_NONE]       = {NULL, 0, false},
    [GESTURE_NOD]        = {G_NOD,        ARRAY_LEN_S(G_NOD),        false},
    [GESTURE_SHAKE]      = {G_SHAKE,      ARRAY_LEN_S(G_SHAKE),      false},
    [GESTURE_TILT]       = {G_TILT,       ARRAY_LEN_S(G_TILT),       false},
    [GESTURE_SCAN]       = {G_SCAN,       ARRAY_LEN_S(G_SCAN),       false},
    [GESTURE_DANCE]      = {G_DANCE,      ARRAY_LEN_S(G_DANCE),      false},
    [GESTURE_WAKE]       = {G_WAKE,       ARRAY_LEN_S(G_WAKE),       false},
    [GESTURE_SLEEP]      = {G_SLEEP,      ARRAY_LEN_S(G_SLEEP),      false},
    [GESTURE_LOOK_LEFT]  = {G_LOOK_LEFT,  ARRAY_LEN_S(G_LOOK_LEFT),  false},
    [GESTURE_LOOK_RIGHT] = {G_LOOK_RIGHT, ARRAY_LEN_S(G_LOOK_RIGHT), false},
    // Centre is the one absolute move: "go back to straight ahead" means an
    // angle, not a nudge, or it would only ever be relative to a drift.
    [GESTURE_CENTER]     = {NULL, 0, true},
};

static volatile sandy_gesture_t s_pending = GESTURE_NONE;
static volatile bool            s_playing;
static TaskHandle_t             s_gesture_task;

bool servo_gesture_active(void) { return s_playing; }

static void _gesture_task(void *arg) {
    (void)arg;
    for (;;) {
        // Wait to be poked rather than polling: a task spinning on a flag for a
        // neck that moves twice an hour is a core doing nothing, expensively.
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);

        sandy_gesture_t g = s_pending;
        if (g <= GESTURE_NONE || g >= GESTURE_COUNT) continue;

        const gesture_def_t *def = &GESTURES[g];
        s_playing = true;

        if (def->absolute_center) {
            servo_set_angle(SERVO_DEFAULT_POS);
            vTaskDelay(pdMS_TO_TICKS(300));
        } else {
            const uint8_t home = servo_get_angle();
            for (size_t i = 0; i < def->count; i++) {
                // A newer gesture cancels this one mid-step: the last thing
                // asked for is what she does.
                if (s_pending != g) break;
                int target = (int)home + def->steps[i].offset;
                if (target < SERVO_SAFE_MIN) target = SERVO_SAFE_MIN;
                if (target > SERVO_SAFE_MAX) target = SERVO_SAFE_MAX;
                servo_set_angle((uint8_t)target);
                vTaskDelay(pdMS_TO_TICKS(def->steps[i].hold_ms));
            }
            // Always come home. Without this a nod every few minutes walks her
            // head off to one side over an evening, and nothing ever puts it back.
            if (s_pending == g) servo_set_angle(home);
        }

        s_playing = false;
        if (s_pending == g) s_pending = GESTURE_NONE;
    }
}

void servo_gesture(sandy_gesture_t g) {
    if (g <= GESTURE_NONE || g >= GESTURE_COUNT) return;
    if (!s_gesture_task) {
        // 2560: it delays and calls servo_set_angle, which does not go deep.
        // Task stacks are internal RAM and internal RAM is what the voice
        // session needs, so this is sized to the work and not rounded up.
        if (xTaskCreate(_gesture_task, "servo_gest", 2560, NULL, 3, &s_gesture_task) != pdPASS) {
            ESP_LOGE(TAG, "gesture task create failed — gestures unavailable");
            s_gesture_task = NULL;
            return;
        }
    }
    s_pending = g;
    xTaskNotifyGive(s_gesture_task);
}
