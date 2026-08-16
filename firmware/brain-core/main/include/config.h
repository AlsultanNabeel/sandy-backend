#pragma once

// ─── Feature flags (bring-up toggles) ──────────────────────────────────────────
// 1 = subsystem enabled, 0 = skipped at boot. Bring the robot up one piece at a
// time: leave only what you've wired set to 1, reflash, test, then enable the
// next. WIFI gates the cloud parts (MQTT / OTA / voice) — they need it.
#define ENABLE_WIFI     1
#define ENABLE_FACE     1   // ST7789 display
#define ENABLE_SERVO    1
#define ENABLE_BUZZER   1   // بيزو سلبي بمخرجين: GPIO 17 + GND
#define ENABLE_SENSOR   0
#define ENABLE_MOTORS   0
#define ENABLE_TOUCH    0
#define ENABLE_MIC      0   // MAX9814 clap mic
#define ENABLE_EARS     0   // stereo sound-direction (temp off; merging into VOICE next)
#define ENABLE_OTA      0   // needs WIFI
#define ENABLE_MQTT     1   // needs WIFI — cloud body control (mood/servo/buzzer/base)
#define ENABLE_VOICE    1   // needs WIFI
#define ENABLE_WAKEWORD 1   // local WakeNet gate for the voice session (needs VOICE)
// نموذج الأوامر المحلية (MultiNet) — مطفي بقرار، والسبب يستاهل يتكتب.
//
// كان بياخد حوالي ٥٨ كيلو من الرام الداخلية. والداخلية ٢٢٧ كيلو كلها، وبتنزل
// لـ ٢٦ بعد ما الواي فاي وكلمة الإيقاظ ياخدوا نصيبهم — فالنموذج لحاله كان
// بياكل أكتر من نصف اللي بيضل. ولما التشفير طلب بضع مئات بايت بنص مكالمة، ما
// لقي: `esp-aes: Failed to allocate memory`.
//
// وعشان ما بيسع مع وصلة الصوت، كان لازم ينفرّغ كل مكالمة ويترجّع بعدها. هاد
// أخّر فتح كل جلسة، وطبع خطأ أحمر كل مرّة.
//
// واللي كان بيشتريه بهاد الثمن: خمستعش عبارة إنجليزية ثابتة زي
// "SANDY TURN ON THE LIGHT". المالك بيحكي عربي، والتطبيق بيعمل نفس الإشي بضغطة.
//
// كلمة الإيقاظ نموذج تاني وأصغر بكتير، وضلّت شغّالة — الفرق إنه بعد ما تصحيها
// بتحكي معها بدل ما تقول عبارة محفوظة.
//
// الكود كله محروس بهاي الراية ومكانه، فرجعتها لواحد بترجّع الميزة كاملة.
#define ENABLE_COMMANDS 0   // local MultiNet "Sandy ..." command words (needs WAKEWORD)
#define ENABLE_SPK_TEST 0   // temporary: triple-beep to verify amp + speaker
#define ENABLE_REMOTE   1   // cable-free dev: OTA upload + serial log over WiFi (needs WIFI)
#define ENABLE_LED      1   // on-board WS2812: idle blue / listening white / talking amber

// ─── GPIO Pins ────────────────────────────────────────────────────────────────
// Mapped for the ESP32-S3-DevKitC-1 / N16R8 (verified against the board's
// broken-out header). Reserved pins that are NOT used here:
//   33-37  → Octal PSRAM on the N16R8 (35/36/37 are on the header but off-limits)
//   0/3/45/46 → strapping pins
//   43/44  → UART0 console (TX/RX)
//   19/20  → native USB D-/D+
//   48     → on-board RGB LED (PIN_W2812 below)

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

// MAX9814 analog mic (clap detection) — ADC1 CH3 = GPIO4 on the S3.
// Separate from the INMP441 voice mic below; this one only watches for claps.
#define PIN_MIC_ADC             4
#define MIC_ADC_CHANNEL         ADC_CHANNEL_3   // GPIO4 = ADC1_CH3 on S3

// TTP223 capacitive touch
#define PIN_TOUCH               14

// WS2812 RGB LED — on-board on the DevKitC-1 N16R8 (GPIO48).
#define PIN_W2812               48

// ST7789 240×240 display — SPI. Any GPIO works via the S3 GPIO matrix; these
// stay clear of the PSRAM/strapping/USB pins above.
#define PIN_TFT_MOSI            40
#define PIN_TFT_SCLK            41
#define PIN_TFT_CS              39
#define PIN_TFT_DC              42
#define PIN_TFT_RST             2
#define PIN_TFT_BLK             1    // backlight PWM
#define TFT_WIDTH               240
#define TFT_HEIGHT              240

// ─── LEDC ─────────────────────────────────────────────────────────────────────
#define LEDC_CH_SERVO           LEDC_CHANNEL_0
#define LEDC_CH_BUZZER          LEDC_CHANNEL_1
#define LEDC_TIMER_SERVO        LEDC_TIMER_0
#define LEDC_TIMER_BUZZER       LEDC_TIMER_1

// ─── Servo ────────────────────────────────────────────────────────────────────
#define SERVO_FREQ_HZ           50
#define SERVO_RESOLUTION        LEDC_TIMER_14_BIT
#define SERVO_MIN_US            500             // pulse width at 0°
#define SERVO_MAX_US            2500            // pulse width at 180°
#define SERVO_SAFE_MIN          5
#define SERVO_SAFE_MAX          175
#define SERVO_DEFAULT_POS       90

// ─── HC-SR04 ─────────────────────────────────────────────────────────────────
#define SENSOR_TIMEOUT_US       6000            // ~1 m max
#define SENSOR_MEDIAN_N         3
#define SENSOR_POLL_MS          200

// ─── Buzzer ───────────────────────────────────────────────────────────────────
#define BUZZER_RESOLUTION       LEDC_TIMER_10_BIT
#define BUZZER_VOLUME           512             // 50% of 10-bit

// ─── Motor watchdog ───────────────────────────────────────────────────────────
#define MOTOR_WATCHDOG_MS       3000

// ─── Mic (clap detection) ─────────────────────────────────────────────────────
#define MIC_SAMPLE_PERIOD_MS    5               // 200 Hz
#define MIC_CLAP_THRESHOLD      2200
#define MIC_CLAP_COOLDOWN_MS    1500

// ─── Touch ────────────────────────────────────────────────────────────────────
#define TOUCH_DEBOUNCE_MS       80

// ─── MQTT ─────────────────────────────────────────────────────────────────────
#define MQTT_STATUS_INTERVAL_MS 5000

// Reported in every heartbeat. Bump it with each flash: without it, "did that
// fix actually reach the board?" is a question nobody can answer from the app,
// and today that question cost an afternoon.
#define SANDY_FW_VERSION "0.9.0"

// Which board this is. Three ESP boards share the house network and take three
// different binaries that are not interchangeable:
//
//   sandy-brain-s3   ESP32-S3    this project (ESP-IDF)   — voice, face, servo
//   sandy-room-node  ESP32       sandy/ (Arduino)         — lights, fan, IR
//   sandy-cam        ESP32-CAM   vision-core/ (Arduino)   — the camera
//
// The flash script requires this exact string from the board's own page before
// it sends a binary. Sending the wrong image is not a mistake anyone notices
// until the board stops booting.
#define SANDY_BOARD_ID "sandy-brain-s3"
#define MQTT_RECONNECT_MS       5000

// ─── Voice: I2S digital mic (INMP441) ──────────────────────────────────────────
#define PIN_I2S_MIC_SCK         5       // BCLK / SCK
#define PIN_I2S_MIC_WS          6       // LRCL / WS
#define PIN_I2S_MIC_SD          7       // DOUT (mic data into the S3)

// ─── Voice: I2S amplifier + speaker (MAX98357) ──────────────────────────────────
#define PIN_I2S_SPK_BCLK        9       // BCLK
#define PIN_I2S_SPK_LRC         10      // LRC / WS
#define PIN_I2S_SPK_DIN         11      // DIN (data from the S3 into the amp)

// Gemini Live: 16 kHz audio in, 24 kHz out.
#define VOICE_IN_RATE           16000
#define VOICE_OUT_RATE          24000
// Mic gain: the mono mix is amplified ×2^(16-this) AFTER the echo canceller.
// 12 (≈+12 dB over 14) so normal speech reaches Gemini's voice-activity
// threshold from a comfortable distance. Capture itself always runs at full
// headroom (>>16, clip-proof): gain at capture used to saturate the mics
// whenever her own speaker (a few cm behind them) played, and a clipped echo
// is nonlinear — the AEC cancelled nothing and she answered her own voice.
#define VOICE_MIC_GAIN_SHIFT    12
// Keep the mic muted this long after Sandy's last audio (avoids echo).
#define VOICE_HALF_DUPLEX_TAIL_MS  400

// ─── Wake word (ESP-SR / WakeNet) ──────────────────────────────────────────────
// Local, always-on keyword spotter that gates the cloud voice session: the
// Gemini link only connects after the wake word and drops after silence, so we
// don't pay for an open session while idle. Built-in model for now
// (wn9_hiandy_tts2 "Hi Andy" — closest to "Sandy", set in sdkconfig.defaults);
// a custom-trained "Sandy" model swaps in later without touching this code.
// Close the session (disconnect Gemini) after this long with no speech.
#define VOICE_SESSION_IDLE_MS      8000
// How long a mid-call link drop is allowed to take before we give up on the
// conversation. One stalled socket write kills the connection; the client
// reconnects in ~5s, so this has to be comfortably longer than that.
#define VOICE_RECONNECT_GRACE_MS   15000
// Mic level (avg abs sample/frame) above which the user counts as still
// talking, to hold the session open. Must sit ABOVE the room's ambient floor
// (seen ~400-1000 on the diag log) or background noise keeps the session from
// ever closing; real speech runs 2500+. Tune with the `diag mic=` log.
// Speech loud enough to count as "the user is still in this conversation". Kept
// equal to VOICE_DUPLEX_GATE_LEVEL on purpose: that gate already decides what is
// a human talking, and when this one sat higher, a normal speaking voice failed
// it and the session hung up mid-sentence while his words were still streaming.
#define VOICE_SESSION_VAD_LEVEL    1500

// With nothing happening for this long, the face drifts off to sleep
// (MOOD_SLEEPY). Any interaction — wake word, proximity, a cloud mood —
// wakes her instantly.
#define FACE_SLEEP_AFTER_MS     (5 * 60 * 1000)

// Turn-toward-sound: on the wake word, point the neck at whoever called.
// Direction comes from the left/right mic energy balance of the wake
// utterance itself. Tune with the `ears:` log line.
#define VOICE_EARS_SWING           35   // max degrees off center (90)
#define VOICE_EARS_INVERT          1    // set 1 if she turns the wrong way

// ─── Acoustic echo cancellation (esp-sr AEC) ──────────────────────────────────
// Subtract Sandy's own speaker audio from the mic signal so she hears the user
// even while she's talking — this is what makes natural barge-in possible.
#define VOICE_AEC_ENABLE           1
#define VOICE_AEC_FILTER_LEN       4    // adaptive filter blocks (esp-sr recommends 4)
// The captured reference leads the acoustic echo by roughly the TX DMA depth
// (~60ms of audio sits in hardware before the amp plays it), so playback
// starts by pre-filling this much silence into the reference queue.
#define VOICE_AEC_REF_DELAY_MS     60
// 1 = the mic keeps streaming to the cloud while she talks (full duplex —
//     talk over her and Gemini interrupts itself). Falls back to half-duplex
//     automatically if the AEC engine failed to start.
// 0 = half-duplex: mute the mic while she talks. The AEC residual was still
//     leaking her own voice back up, so she'd hear herself and answer twice.
//     Half-duplex kills the echo/double-reply for sure (cost: no barge-in —
//     wait for her to finish). Re-enable once the speaker is physically moved
//     away from the mics so the AEC has less echo to cancel.
#define VOICE_AEC_FULL_DUPLEX      0
// While she talks, mic frames only go to the cloud above this (cleaned)
// level — the AEC residual sits low, a real interrupting voice doesn't.
// The final guard against her answering her own echo. Tune with `diag mic=`
// readings taken while she speaks.
#define VOICE_DUPLEX_GATE_LEVEL    1500
// ...and only after this many consecutive over-gate batches (~33ms each):
// a lone spike is echo residual sneaking through, a 100ms run is a human.
// The pending batches are stashed and sent once the run qualifies, so the
// start of the interruption still reaches Gemini.
#define VOICE_DUPLEX_GATE_RUN      3
