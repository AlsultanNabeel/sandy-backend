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

// Blocks ~20 ms per degree, so only the gesture task calls it (the mic task
// stalled audio, and two callers raced on s_angle).
static void _move_blocking(uint8_t angle);

// 14-bit LEDC at 50 Hz (20000 us period)
static uint32_t _angle_to_duty(uint8_t angle) {
    uint32_t pw_us = SERVO_MIN_US +
        (uint32_t)angle * (SERVO_MAX_US - SERVO_MIN_US) / 180;
    return (pw_us * ((1 << 14) - 1)) / 20000;
}

static TaskHandle_t s_gesture_task;
static bool _ensure_task(void);

// The duty keeps the last position, so re-arming never jumps.
static bool s_relaxed;

static void _relax(void) {
    if (s_relaxed) return;
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CH_SERVO, 0);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CH_SERVO);
    s_relaxed = true;
}

static void _arm(void) {
    if (!s_relaxed) return;
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CH_SERVO, _angle_to_duty(s_angle));
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CH_SERVO);
    s_relaxed = false;
}

esp_err_t servo_init(void) {
    // Read the saved angle first so the first pulse is already there (no snap to centre).
    uint8_t saved = SERVO_DEFAULT_POS;
    if (nvs_load_servo_angle(&saved) == ESP_OK) {
        ESP_LOGI(TAG, "restored angle=%d from NVS", saved);
    }
    if (saved < SERVO_SAFE_MIN) saved = SERVO_SAFE_MIN;
    if (saved > SERVO_SAFE_MAX) saved = SERVO_SAFE_MAX;
    s_angle = saved;

    ledc_timer_config_t timer = {
        .speed_mode      = LEDC_LOW_SPEED_MODE,
        .duty_resolution = SERVO_RESOLUTION,
        .timer_num       = LEDC_TIMER_SERVO,
        .freq_hz         = SERVO_FREQ_HZ,
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    esp_err_t err = ledc_timer_config(&timer);
    if (err != ESP_OK) return err;

    ledc_channel_config_t ch = {
        .gpio_num   = PIN_SERVO,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel    = LEDC_CH_SERVO,
        .timer_sel  = LEDC_TIMER_SERVO,
        .duty       = _angle_to_duty(saved),
        .hpoint     = 0,
        .flags      = { .output_invert = 0 },
    };
    err = ledc_channel_config(&ch);
    if (err != ESP_OK) return err;

    // Settle, then the gesture task relaxes the idle neck.
    if (_ensure_task()) xTaskNotifyGive(s_gesture_task);
    return ESP_OK;
}

static void _move_blocking(uint8_t angle) {
    if (angle < SERVO_SAFE_MIN) angle = SERVO_SAFE_MIN;
    if (angle > SERVO_SAFE_MAX) angle = SERVO_SAFE_MAX;
    _arm();
    if (angle == s_angle) return;

    // Sine ease in-out
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
    // Deferred: flash writes on every move were resetting the board (sandy_nvs.h).
    nvs_save_deferred("sandy", "servo_pos", NVS_VAL_U8, angle);
    ESP_LOGI(TAG, "angle=%d", angle);
}

uint8_t servo_get_angle(void) { return s_angle; }

// ── Gestures (see sandy_servo.h) ──

typedef struct { int8_t offset; uint16_t hold_ms; } step_t;

// Offsets from the current angle, not absolute angles.
static const step_t G_NOD[]        = {{-18,140},{0,120},{-18,140},{0,160}};
static const step_t G_SHAKE[]      = {{-22,130},{22,130},{-16,120},{16,120},{0,150}};
static const step_t G_TILT[]       = {{-26,600},{0,220}};
static const step_t G_SCAN[]       = {{-55,700},{55,1200},{0,600}};
static const step_t G_DANCE[]      = {{-20,180},{20,180},{-20,180},{20,180},
                                      {-12,160},{12,160},{0,200}};
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
    // Centre is the one absolute move.
    [GESTURE_CENTER]     = {NULL, 0, true},
};

static volatile sandy_gesture_t s_pending = GESTURE_NONE;
static volatile int16_t         s_goto = -1;    // pending absolute move, or -1

static void _gesture_task(void *arg) {
    (void)arg;
    for (;;) {
        // No request for SERVO_RELAX_MS after the last move: stop the pulses.
        if (!ulTaskNotifyTake(pdTRUE, pdMS_TO_TICKS(SERVO_RELAX_MS))) {
            _relax();
            ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        }

        // A plain goto (voice turn, app slider); a gesture queued after it still plays.
        int16_t target = s_goto;
        if (target >= 0) {
            s_goto = -1;
            _move_blocking((uint8_t)target);
        }

        sandy_gesture_t g = s_pending;
        if (g <= GESTURE_NONE || g >= GESTURE_COUNT) continue;

        const gesture_def_t *def = &GESTURES[g];

        if (def->absolute_center) {
            _move_blocking(SERVO_DEFAULT_POS);
            vTaskDelay(pdMS_TO_TICKS(300));
        } else {
            const uint8_t home = servo_get_angle();
            for (size_t i = 0; i < def->count; i++) {
                // A newer request cancels this one mid-step.
                if (s_pending != g || s_goto >= 0) break;
                int target = (int)home + def->steps[i].offset;
                if (target < SERVO_SAFE_MIN) target = SERVO_SAFE_MIN;
                if (target > SERVO_SAFE_MAX) target = SERVO_SAFE_MAX;
                _move_blocking((uint8_t)target);
                vTaskDelay(pdMS_TO_TICKS(def->steps[i].hold_ms));
            }
            // Always return home, or repeated gestures drift the head.
            if (s_pending == g && s_goto < 0) _move_blocking(home);
        }

        if (s_pending == g) s_pending = GESTURE_NONE;
        // More work arrived: loop again without waiting.
        if (s_goto >= 0 || s_pending != GESTURE_NONE) xTaskNotifyGive(s_gesture_task);
    }
}

static bool _ensure_task(void) {
    if (s_gesture_task) return true;
    // Sized to the work: task stacks are internal RAM, which voice needs.
    if (xTaskCreate(_gesture_task, "servo_gest", 2560, NULL, 3, &s_gesture_task) != pdPASS) {
        ESP_LOGE(TAG, "gesture task create failed — neck unavailable");
        s_gesture_task = NULL;
        return false;
    }
    return true;
}

void servo_gesture(sandy_gesture_t g) {
    if (g <= GESTURE_NONE || g >= GESTURE_COUNT) return;
    if (!_ensure_task()) return;
    s_pending = g;
    xTaskNotifyGive(s_gesture_task);
}

void servo_move_to(uint8_t angle) {
    if (!_ensure_task()) return;
    s_goto = angle;
    s_pending = GESTURE_NONE;   // the last thing asked for is what she does
    xTaskNotifyGive(s_gesture_task);
}
