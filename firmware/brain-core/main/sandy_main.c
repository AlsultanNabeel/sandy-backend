#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "esp_log.h"
#include "esp_task_wdt.h"
#include "esp_system.h"
#include "config.h"
#include "sandy_types.h"
#include "sandy_nvs.h"
#include "sandy_wifi.h"
#include "sandy_provision.h"
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
#include "sandy_audio_ctl.h"

static const char *TAG = "main";

// A part that fails to come up must not take the robot with it. ESP_ERROR_CHECK
// around these turned a loose display ribbon, a clashing LEDC timer or an
// unplugged sensor into an abort — i.e. a boot loop with no face, no wake word
// and no log of what actually went wrong. Same principle as buzzer_play going
// quiet when the buzzer isn't fitted, one level up: log it, skip it, keep going.
#define TRY_INIT(name, call)                                                   \
    do {                                                                       \
        esp_err_t _e = (call);                                                 \
        if (_e != ESP_OK) {                                                    \
            ESP_LOGE(TAG, "%s init failed (%s) — running without it",          \
                     (name), esp_err_to_name(_e));                             \
        }                                                                      \
    } while (0)

// Global mood state — written by MQTT/touch/mic, read by face/buzzer
volatile sandy_mood_t g_current_mood = MOOD_IDLE;

#if ENABLE_SENSOR && ENABLE_FACE
// Permanent behaviour: when something comes close, Sandy looks surprised.
// Hands off while a voice conversation is running — the voice link drives the
// face then (listening/talking), and this loop would stomp it every 300ms.
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
        // Edge-triggered, not level-triggered: the old "set IDLE every 300ms"
        // stomped every mood that came from anywhere else (MQTT mood commands
        // appeared broken because of this) and would never let her fall asleep.
        if (near && !was_near) face_set_mood(MOOD_SURPRISED);
        if (!near && was_near) face_set_mood(MOOD_IDLE);
        was_near = near;
        vTaskDelay(pdMS_TO_TICKS(300));
    }
}
#endif

#if ENABLE_MQTT
// MQTT joins ~20s late on purpose: its TLS handshake right at boot stacked a
// power peak on top of the WiFi/display/voice bring-up and browned out weaker
// supplies (power bank / laptop USB). Body control can afford to be late.
static void _mqtt_late_start(void *arg) {
    vTaskDelay(pdMS_TO_TICKS(20000));
    if (mqtt_sandy_start() != ESP_OK) {
        ESP_LOGE(TAG, "MQTT failed to start — running without cloud body control");
    }
    vTaskDelete(NULL);
}
#endif

void app_main(void) {
    // reset_reason separates a brownout from a panic from a plain power-on at
    // a glance — the first thing to check when the board reboots on its own.
    ESP_LOGI(TAG, "Sandy Brain S3 — booting (reset_reason=%d)", (int)esp_reset_reason());

    // ── Core services ─────────────────────────────────────────────────────────
    // NVS only holds the saved neck angle here; losing it costs a default pose.
    TRY_INIT("nvs", nvs_sandy_init());
#if ENABLE_WIFI
    TRY_INIT("wifi", wifi_sandy_start());
#endif
#if ENABLE_PROVISION
    // After wifi_sandy_start, which returns as soon as the radio is up: this
    // watches whether an association actually happens and raises the setup
    // access point if none does. Starting it here rather than inside the Wi-Fi
    // module keeps that module about one thing — the radio — and this one about
    // the thing that has to keep working when the radio has nowhere to go.
    TRY_INIT("provision", provision_init());
#endif
#if ENABLE_REMOTE
    TRY_INIT("remote", remote_init());   // OTA + remote log over WiFi
    // Repeat the reset reason now that the remote log buffer exists — the
    // line at the top of app_main is UART-only (printed before the buffer).
    ESP_LOGI(TAG, "reset_reason=%d (9=brownout 4=panic 1=power-on)", (int)esp_reset_reason());
#endif

    // Outside the ENABLE_REMOTE guard on purpose. The bootloader marks a fresh
    // image PENDING_VERIFY whether or not this build has an update server, so an
    // image that never runs this call would roll back on every single reboot,
    // forever — turning a config flag into a brick. The function itself decides
    // what "healthy" can mean in this build.
    //
    // Here and not later: it only has to prove the board can still be *reached*,
    // and Wi-Fi plus the update server are up by now. Tying it to the peripherals
    // would let a dead servo roll back firmware you could otherwise fix remotely.
    ota_start_health_watch();

    // ── Peripherals ───────────────────────────────────────────────────────────
#if ENABLE_FACE
    TRY_INIT("face", face_init());
#endif
#if ENABLE_LED
    led_init();   // already non-fatal: a dead status LED shouldn't stop the robot
#endif
    // After the face and the LED, because it drives both: from here on every
    // failure in any subsystem has somewhere to show itself.
    status_init();
    // Before the mic and voice tasks start reading the gains, and before MQTT
    // can be told to change them.
    audio_ctl_init();
#if ENABLE_SERVO
    TRY_INIT("servo", servo_init());
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
#if ENABLE_OTA
    TRY_INIT("ota", ota_init());
#endif

    // ── Network ───────────────────────────────────────────────────────────────
#if ENABLE_MQTT
    xTaskCreate(_mqtt_late_start, "mqtt_late", 4096, NULL, 3, NULL);
#endif

    // ── Voice link (waits for Wi-Fi, then connects to /voice) ───────────────────
#if ENABLE_VOICE
    TRY_INIT("voice", voice_init());
#endif

    ESP_LOGI(TAG, "all systems go");

#if ENABLE_BUZZER
    // Short startup chime so we know the board booted.
    buzzer_play(MELODY_BOOT);
#endif

#if ENABLE_SENSOR && ENABLE_FACE
    xTaskCreate(_proximity_task, "proximity", 3072, NULL, 3, NULL);
#endif

    // Watchdog on main task (5s — configured in sdkconfig.defaults)
    esp_task_wdt_add(NULL);
    for (;;) {
        esp_task_wdt_reset();
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
