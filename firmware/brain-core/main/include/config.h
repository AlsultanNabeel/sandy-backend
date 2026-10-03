#pragma once

// ─── Feature flags ───
// 1 = enabled at boot. WIFI gates MQTT / OTA / voice.
#define ENABLE_WIFI     1
#define ENABLE_FACE     1   // ST7789 display
#define ENABLE_SERVO    1
#define ENABLE_BUZZER   1   // بيزو سلبي بمخرجين: GPIO 17 + GND
#define ENABLE_SENSOR   0
#define ENABLE_MOTORS   0
#define ENABLE_TOUCH    0
#define ENABLE_MIC      0   // MAX9814 clap mic
#define ENABLE_EARS     0   // stereo sound direction (off for now)
#define ENABLE_OTA      1   // needs WIFI — signed releases from the server
#define ENABLE_MQTT     1   // needs WIFI — cloud body control
#define ENABLE_VOICE    1   // needs WIFI
#define ENABLE_WAKEWORD 1   // local WakeNet gate for voice (needs VOICE)
// أوامر MultiNet المحلية مطفية: كانت تاخد ~٥٨ كيلو من الرام الداخلية وتسبب
// `esp-aes: Failed to allocate memory` بنص المكالمة. رجّعها لـ 1 بترجع الميزة كاملة.
#define ENABLE_COMMANDS 0   // local MultiNet "Sandy ..." command words (needs WAKEWORD)
#define ENABLE_SPK_TEST 0   // triple-beep amp + speaker check
// Dev only: unauthenticated image upload + log stream on the LAN.
// نسخة البيع (-DSANDY_RETAIL=1، اللي بيبنيها ملف النشر) بتسكّره لحالها.
#if defined(SANDY_RETAIL) && SANDY_RETAIL
#define ENABLE_REMOTE   0
#else
#define ENABLE_REMOTE   1   // OTA upload + serial log over WiFi (needs WIFI)
#endif
#define ENABLE_PROVISION 1  // needs WIFI — SoftAP setup page when no network answers
// طويل بقصد: الراوتر ممكن يتأخر دقيقة بالصبح، والتزويد ما لازم يشتغل عالفاضي.
#define PROVISION_WINDOW_MS  90000
#define ENABLE_IR       1   // needs MQTT — IR learn + replay over RMT
#define ENABLE_LED      1   // on-board WS2812 status LED

// ─── GPIO Pins (ESP32-S3-DevKitC-1 N16R8) ───
// Do not use: 33-37 octal PSRAM, 0/3/45/46 strapping, 43/44 UART0, 19/20 USB, 48 RGB LED.

// Servo (neck) — SG90 via LEDC PWM
#define PIN_SERVO               16

// HC-SR04 ultrasonic distance sensor
#define PIN_SENSOR_TRIG         15
#define PIN_SENSOR_ECHO         13

// Buzzer — LEDC PWM
#define PIN_BUZZER              17

// L298N motor driver
#define PIN_MOTOR_IN1           18
#define PIN_MOTOR_IN2           8
#define PIN_MOTOR_IN3           12
#define PIN_MOTOR_IN4           47

// MAX9814 analog mic for clap detection (ADC1 CH3), separate from the INMP441.
#define PIN_MIC_ADC             4
#define MIC_ADC_CHANNEL         ADC_CHANNEL_3   // GPIO4 = ADC1_CH3 on S3

// TTP223 capacitive touch
#define PIN_TOUCH               14

// WS2812 RGB LED, on-board.
#define PIN_W2812               48

// أرجل بعيدة عن أرجل الإقلاع واليو إس بي: رِجل إقلاع بتخرّب الإقلاع.
#define PIN_IR_TX               21   // IR LED (through a transistor, not direct)
#define PIN_IR_RX               38   // VS1838B / TSOP38238 data

// ST7789 240×240 display over SPI, clear of the reserved pins above.
#define PIN_TFT_MOSI            40
#define PIN_TFT_SCLK            41
#define PIN_TFT_CS              39
#define PIN_TFT_DC              42
#define PIN_TFT_RST             2
#define PIN_TFT_BLK             1    // backlight PWM
#define TFT_WIDTH               240
#define TFT_HEIGHT              240

// ─── LEDC ───
#define LEDC_CH_SERVO           LEDC_CHANNEL_0
#define LEDC_CH_BUZZER          LEDC_CHANNEL_1
#define LEDC_TIMER_SERVO        LEDC_TIMER_0
#define LEDC_TIMER_BUZZER       LEDC_TIMER_1

// ─── Servo ───
#define SERVO_FREQ_HZ           50
#define SERVO_RESOLUTION        LEDC_TIMER_14_BIT
#define SERVO_MIN_US            500             // pulse width at 0°
#define SERVO_MAX_US            2500            // pulse width at 180°
// The neck's travel: past these the head hits the body and the servo stalls.
// Gestures are ±55 at most, so 20..160 keeps them inside. Tune per build.
#define SERVO_SAFE_MIN          20
#define SERVO_SAFE_MAX          160
// Stop pulses after the neck rests: a held servo hums and draws current; gearing holds it.
#define SERVO_RELAX_MS          700
#define SERVO_DEFAULT_POS       90

// ─── HC-SR04 ───
#define SENSOR_TIMEOUT_US       6000            // ~1 m max
#define SENSOR_MEDIAN_N         3
#define SENSOR_POLL_MS          200

// ─── Buzzer ───
#define BUZZER_RESOLUTION       LEDC_TIMER_10_BIT
#define BUZZER_VOLUME           512             // 50% of 10-bit

// ─── Motor watchdog ───
#define MOTOR_WATCHDOG_MS       3000

// ─── Mic (clap detection) ───
#define MIC_SAMPLE_PERIOD_MS    5               // 200 Hz
#define MIC_CLAP_THRESHOLD      2200
#define MIC_CLAP_COOLDOWN_MS    1500

// ─── Touch ───
#define TOUCH_DEBOUNCE_MS       80

// ─── MQTT ───
#define MQTT_STATUS_INTERVAL_MS 5000

// ─── Health (sandy_health.c) ───
// This many crash restarts (panic or watchdog) without a run of HEALTH_STABLE_MS between
// them, and she boots in safe mode: network and updates only, no voice, no body.
#define HEALTH_SAFE_AFTER_CRASHES  3
#define HEALTH_STABLE_MS           (10 * 60 * 1000)

// Reported in every heartbeat. Bump with each flash.
#define SANDY_FW_VERSION "0.11.2"

// The flash script checks this against the board before sending a binary:
// sandy-brain-s3 (this), sandy-room-node, sandy-cam are not interchangeable.
#define SANDY_BOARD_ID "sandy-brain-s3"
#define MQTT_RECONNECT_MS       5000

// ─── Voice: I2S digital mic (INMP441) ───
#define PIN_I2S_MIC_SCK         5       // BCLK / SCK
#define PIN_I2S_MIC_WS          6       // LRCL / WS
#define PIN_I2S_MIC_SD          7       // DOUT (mic data into the S3)

// ─── Voice: I2S amplifier + speaker (MAX98357) ───
#define PIN_I2S_SPK_BCLK        9       // BCLK
#define PIN_I2S_SPK_LRC         10      // LRC / WS
#define PIN_I2S_SPK_DIN         11      // DIN (data from the S3 into the amp)

// 16 kHz audio in, 24 kHz out.
#define VOICE_IN_RATE           16000
#define VOICE_OUT_RATE          24000
// Output gain ×2^(16-this), applied AFTER the audio front end. Capture stays at
// full headroom: gain there clipped on her own speaker and broke echo cancelling.
#define VOICE_MIC_GAIN_SHIFT    12
// She counts as talking this long after her last audio (barge-in rules apply).
#define VOICE_HALF_DUPLEX_TAIL_MS  400

// ─── Wake word (ESP-SR WakeNet) ───
// Gates the cloud session (model set in sdkconfig.defaults).
// Close the session after this long with no speech.
#define VOICE_SESSION_IDLE_MS      8000
// Allowed time for a mid-call reconnect (~5 s) before giving up the conversation.
#define VOICE_RECONNECT_GRACE_MS   15000
// Speech over her this long (the front end's voice detector) stops her: long enough
// that a cough or a word to someone else does not, short enough to feel instant.
#define VOICE_BARGE_MS             200
// The detector calls speech over this long after the last word (esp-sr vad_min_noise_ms).
#define VOICE_VAD_END_MS           300
// Only the person who said the wake word: during a session, speech counts when it is at
// least this share of how loud the caller is (set by the wake word, then following their
// own speech, so walking away a few metres keeps them). Voices from another room are far
// quieter (the family kept a session open for minutes and became questions).
#define VOICE_NEAR_PCT             30
// Floor for that bar, so a whispered wake word does not open the room.
#define VOICE_NEAR_MIN             600

// Idle this long → MOOD_SLEEPY; any interaction wakes her.
#define FACE_SLEEP_AFTER_MS     (5 * 60 * 1000)

// On the wake word, turn the neck toward the louder mic. Tune with the `ears:` log.
#define VOICE_EARS_SWING           35   // max degrees off center (90)
#define VOICE_EARS_INVERT          1    // set 1 if she turns the wrong way

// ─── Echo cancellation (inside the audio front end) ───
// The reference leads the real echo by the TX DMA depth (~60 ms), so pre-fill that much silence.
#define VOICE_REF_DELAY_MS         60
