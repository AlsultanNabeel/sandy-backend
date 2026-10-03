#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_system.h"
#include "config.h"
#include "sandy_types.h"
#include "sandy_nvs.h"
#include "sandy_identity.h"
#include "sandy_wifi.h"
#include "sandy_provision.h"
#include "sandy_ir.h"
#include "sandy_servo.h"
#include "sandy_buzzer.h"
#include "sandy_sensor.h"
#include "sandy_motors.h"
#include "sandy_touch.h"
#include "sandy_mic.h"
#include "sandy_face.h"
#include "sandy_mqtt.h"
#include "sandy_ota.h"
#include "sandy_voice.h"
#include "sandy_ears.h"
#include "sandy_spktest.h"
#include "sandy_remote.h"
#include "sandy_led.h"
#include "sandy_status.h"
#include "sandy_health.h"
#include "sandy_audio_ctl.h"

static const char *TAG = "main";

// Log and continue: a failed part must not boot-loop the whole robot.
#define TRY_INIT(name, call)                                                   \
    do {                                                                       \
        esp_err_t _e = (call);                                                 \
        if (_e != ESP_OK) {                                                    \
            ESP_LOGE(TAG, "%s init failed (%s) — running without it",          \
                     (name), esp_err_to_name(_e));                             \
        }                                                                      \
    } while (0)

// The same, for a part whose failure must show: its status is set as well.
#define TRY_PART(name, call, part, st)                                         \
    do {                                                                       \
        esp_err_t _e = (call);                                                 \
        if (_e != ESP_OK) {                                                    \
            ESP_LOGE(TAG, "%s init failed (%s) — running without it",          \
                     (name), esp_err_to_name(_e));                             \
            status_set((part), (st));                                          \
        }                                                                      \
    } while (0)

volatile sandy_mood_t g_current_mood = MOOD_IDLE;

#if ENABLE_SENSOR && ENABLE_FACE
// Look surprised when something comes close, except during a voice session.
static void _proximity_task(void *arg) {
    bool was_near = false;
    for (;;) {
#if ENABLE_VOICE
        if (voice_session_is_active()) {
            vTaskDelay(pdMS_TO_TICKS(300));
            continue;
        }
#endif
        uint32_t d = sensor_get_distance_cm();
        bool near = (d > 0 && d < 25);
        // Edge-triggered so it doesn't stomp moods set elsewhere.
        if (near && !was_near) face_set_mood(MOOD_SURPRISED);
        if (!near && was_near) face_set_mood(MOOD_IDLE);
        was_near = near;
        vTaskDelay(pdMS_TO_TICKS(300));
    }
}
#endif

#if ENABLE_MQTT
// MQTT starts ~20 s late: its TLS at boot browned out weak supplies.
static void _mqtt_late_start(void *arg) {
    vTaskDelay(pdMS_TO_TICKS(20000));
    if (mqtt_sandy_start() != ESP_OK) {
        ESP_LOGE(TAG, "MQTT failed to start — running without cloud body control");
    }
    vTaskDelete(NULL);
}
#endif

void app_main(void) {
    // Tells brownout from panic from power-on.
    ESP_LOGI(TAG, "Sandy Brain S3 — booting (reset_reason=%d)", (int)esp_reset_reason());
    // Before anything that could crash again: decides safe mode.
    health_boot();
    const bool safe = health_safe_mode();

    // ── Core services ──
    TRY_INIT("nvs", nvs_sandy_init());
    // See sandy_identity.h.
    TRY_INIT("identity", identity_init());
#if ENABLE_WIFI
    TRY_INIT("wifi", wifi_sandy_start());
#endif
#if ENABLE_IR
    // Before MQTT, which dispatches the `ir` output.
    if (!safe) TRY_INIT("ir", ir_init());
#endif
#if ENABLE_PROVISION
    // Raises the setup AP if no association happens.
    TRY_INIT("provision", provision_init());
#endif
#if ENABLE_REMOTE
    TRY_INIT("remote", remote_init());   // OTA + remote log over WiFi
    // Again for the remote log (the first line was UART-only).
    ESP_LOGI(TAG, "reset_reason=%d (9=brownout 4=panic 1=power-on)", (int)esp_reset_reason());
#endif

    // Outside ENABLE_REMOTE: without this call a PENDING_VERIFY image would roll back
    // on every reboot. Early, because health only means "still reachable".
    ota_start_health_watch();

    if (safe) {
        // Network and updates only: whatever kept crashing stays off until an update
        // or a power cut. The heartbeat says so.
        status_init();
        status_set(SANDY_PART_SYSTEM, SANDY_ST_SAFE_MODE);
    } else {
        // ── Peripherals ──
#if ENABLE_FACE
        TRY_PART("face", face_init(), SANDY_PART_SCREEN, SANDY_ST_SCREEN_OFF);
#endif
#if ENABLE_LED
        led_init();   // non-fatal
#endif
        // After face and LED, which it drives.
        status_init();
        // Before mic, voice and MQTT use the gains.
        audio_ctl_init();
#if ENABLE_SERVO
        TRY_PART("servo", servo_init(), SANDY_PART_NECK, SANDY_ST_NECK_OFF);
#endif
#if ENABLE_BUZZER
        TRY_INIT("buzzer", buzzer_init());
#endif
#if ENABLE_SENSOR
        TRY_INIT("sensor", sensor_init());
#endif
#if ENABLE_MOTORS
        TRY_INIT("motors", motors_init());
#endif
#if ENABLE_TOUCH
        TRY_INIT("touch", touch_init());
#endif
#if ENABLE_MIC
        TRY_INIT("mic", mic_init());
#endif
#if ENABLE_EARS
        TRY_INIT("ears", ears_init());
#endif
#if ENABLE_SPK_TEST
        TRY_INIT("spk_test", spktest_init());
#endif
    }
#if ENABLE_OTA
    TRY_INIT("ota", ota_init());
    ota_updates_start();
#endif

    // ── Network ──
#if ENABLE_MQTT
    xTaskCreate(_mqtt_late_start, "mqtt_late", 4096, NULL, 3, NULL);
#endif

    if (!safe) {
        // ── Voice link ──
#if ENABLE_VOICE
        TRY_INIT("voice", voice_init());
#endif
#if ENABLE_BUZZER
        buzzer_play(MELODY_BOOT);
#endif
#if ENABLE_SENSOR && ENABLE_FACE
        xTaskCreate(_proximity_task, "proximity", 3072, NULL, 3, NULL);
#endif
    }

    ESP_LOGI(TAG, "%s", safe ? "safe mode — network and updates only" : "all systems go");

    health_watch();
    for (;;) {
        health_feed();
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
