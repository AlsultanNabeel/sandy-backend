#include "sandy_buzzer.h"
#include "config.h"
#include "driver/ledc.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

static const char *TAG = "buzzer";

#define ARRAY_LEN(a) (sizeof(a) / sizeof((a)[0]))

typedef struct { uint32_t freq; uint32_t ms; } note_t;

// freq=0 → rest
static const note_t BOOT[]    = {{523,100},{659,100},{784,150},{0,50},{1047,200}};
static const note_t HAPPY[]   = {{784,100},{880,100},{1047,200}};
static const note_t CURIOUS[] = {{523,80},{587,80},{659,80},{698,120}};
static const note_t SAD[]     = {{494,200},{440,200},{392,300}};
static const note_t ALERT[]   = {{880,100},{0,50},{880,100},{0,50},{880,150}};
static const note_t ERR[]     = {{330,200},{0,50},{294,200},{0,50},{262,300}};
// Focus cues: start rises, break pauses, end descends.
static const note_t FOC_START[] = {{523,90},{659,90},{784,90},{988,220}};
static const note_t FOC_BREAK[] = {{784,120},{0,60},{587,160}};
static const note_t FOC_END[]   = {{988,120},{784,120},{659,120},{523,260}};

// ── نغمات إضافية ──
static const note_t HELLO[]     = {{659,90},{784,90},{988,160}};
static const note_t BYE[]       = {{988,110},{784,110},{523,240}};
static const note_t YES[]       = {{784,80},{1047,160}};
static const note_t NO[]        = {{523,110},{392,200}};
static const note_t THINKING[]  = {{659,60},{0,90},{659,60},{0,90},{659,60}};
static const note_t CELEBRATE[] = {{523,90},{659,90},{784,90},{1047,110},{0,60},
                                   {1047,90},{1319,260}};
static const note_t NOTIFY[]    = {{880,90},{0,60},{1047,140}};
static const note_t LOWBATT[]   = {{440,180},{0,80},{392,180},{0,80},{330,300}};

typedef struct { const note_t *notes; size_t count; } melody_def_t;
static const melody_def_t s_defs[MELODY_COUNT] = {
    [MELODY_NONE]    = {NULL,  0},
    [MELODY_BOOT]    = {BOOT,    ARRAY_LEN(BOOT)},
    [MELODY_HAPPY]   = {HAPPY,   ARRAY_LEN(HAPPY)},
    [MELODY_CURIOUS] = {CURIOUS, ARRAY_LEN(CURIOUS)},
    [MELODY_SAD]     = {SAD,     ARRAY_LEN(SAD)},
    [MELODY_ALERT]   = {ALERT,   ARRAY_LEN(ALERT)},
    [MELODY_ERROR]   = {ERR,     ARRAY_LEN(ERR)},
    [MELODY_FOCUS_START] = {FOC_START, ARRAY_LEN(FOC_START)},
    [MELODY_FOCUS_BREAK] = {FOC_BREAK, ARRAY_LEN(FOC_BREAK)},
    [MELODY_FOCUS_END]   = {FOC_END,   ARRAY_LEN(FOC_END)},
    // ARRAY_LEN مش رقم مكتوب: العدد الغلط بيقرا خارج المصفوفة.
    [MELODY_HELLO]     = {HELLO,     ARRAY_LEN(HELLO)},
    [MELODY_BYE]       = {BYE,       ARRAY_LEN(BYE)},
    [MELODY_YES]       = {YES,       ARRAY_LEN(YES)},
    [MELODY_NO]        = {NO,        ARRAY_LEN(NO)},
    [MELODY_THINKING]  = {THINKING,  ARRAY_LEN(THINKING)},
    [MELODY_CELEBRATE] = {CELEBRATE, ARRAY_LEN(CELEBRATE)},
    [MELODY_NOTIFY]    = {NOTIFY,    ARRAY_LEN(NOTIFY)},
    [MELODY_LOWBATT]   = {LOWBATT,   ARRAY_LEN(LOWBATT)},
};

static QueueHandle_t s_q;

static void _note(uint32_t freq, uint32_t ms) {
    if (freq == 0) {
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CH_BUZZER, 0);
    } else {
        ledc_set_freq(LEDC_LOW_SPEED_MODE, LEDC_TIMER_BUZZER, freq);
        ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CH_BUZZER, BUZZER_VOLUME);
    }
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CH_BUZZER);
    vTaskDelay(pdMS_TO_TICKS(ms));
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CH_BUZZER, 0);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CH_BUZZER);
}

static void _task(void *arg) {
    sandy_melody_t m;
    for (;;) {
        if (xQueueReceive(s_q, &m, portMAX_DELAY) != pdTRUE) continue;
        const melody_def_t *def = &s_defs[m < MELODY_COUNT ? m : MELODY_NONE];
        for (size_t i = 0; i < def->count; i++) {
            sandy_melody_t next;
            if (xQueuePeek(s_q, &next, 0) == pdTRUE) {
                // Preempt with the newer melody
                xQueueReceive(s_q, &next, 0);
                m = next;
                def = &s_defs[m < MELODY_COUNT ? m : MELODY_NONE];
                i = (size_t)-1;
                continue;
            }
            _note(def->notes[i].freq, def->notes[i].ms);
        }
    }
}

esp_err_t buzzer_init(void) {
    ledc_timer_config_t timer = {
        .speed_mode      = LEDC_LOW_SPEED_MODE,
        .duty_resolution = BUZZER_RESOLUTION,
        .timer_num       = LEDC_TIMER_BUZZER,
        .freq_hz         = 2000,
        .clk_cfg         = LEDC_AUTO_CLK,
    };
    esp_err_t err = ledc_timer_config(&timer);
    if (err != ESP_OK) return err;

    ledc_channel_config_t ch = {
        .gpio_num   = PIN_BUZZER,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel    = LEDC_CH_BUZZER,
        .timer_sel  = LEDC_TIMER_BUZZER,
        .duty       = 0,
        .hpoint     = 0,
    };
    err = ledc_channel_config(&ch);
    if (err != ESP_OK) return err;

    // s_q stays NULL unless the task runs, so a failed start is silence.
    QueueHandle_t q = xQueueCreate(3, sizeof(sandy_melody_t));
    if (!q) return ESP_ERR_NO_MEM;
    s_q = q;
    if (xTaskCreate(_task, "buzzer", 2048, NULL, 5, NULL) != pdPASS) {
        s_q = NULL;
        vQueueDelete(q);
        return ESP_ERR_NO_MEM;
    }
    ESP_LOGI(TAG, "ready");
    return ESP_OK;
}

// Called regardless of ENABLE_BUZZER; sending to a NULL queue would assert and reboot.
void buzzer_play(sandy_melody_t melody) {
    if (!s_q) return;
    xQueueSend(s_q, &melody, 0);
}
