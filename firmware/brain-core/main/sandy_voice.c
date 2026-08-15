// Real-time voice link: I2S mic/speaker <-> /voice WebSocket (Gemini Live).
//
// Protocol (matches cloud/app/api/voice_ws.py):
//   1. Connect (WSS) and send a hello frame:
//        {"type":"hello","device_id":"...","ts":<unix_ms>,"hmac":"<hex>"}
//        hmac = HMAC-SHA256(SANDY_WS_HMAC_KEY, device_id + str(ts))
//   2. Wait for {"type":"auth_ok"}.
//   3. Mic up: binary PCM, 16-bit LE, 16 kHz mono.
//      Sandy down: binary PCM, 16-bit LE, 24 kHz mono.
//      Control frames (text JSON): {"type":"end_turn"} / {"type":"error",...}.
//
// Half-duplex: we stop sending the mic while Sandy is talking, otherwise the
// speaker leaks back into the mic and she answers her own voice.

#include "sandy_voice.h"
#include "config.h"
#include "secrets.h"

#include <stdlib.h>
#include <string.h>
#include <sys/time.h>
#include <time.h>

#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/stream_buffer.h"
#include "freertos/semphr.h"

#include "esp_log.h"
#include "esp_timer.h"
#include "esp_websocket_client.h"
#include "esp_crt_bundle.h"
#include "esp_netif_sntp.h"
#include "driver/i2s_std.h"
#include "mbedtls/md.h"
#include "esp_heap_caps.h"

#if ENABLE_WAKEWORD
#include "esp_wn_iface.h"
#include "esp_wn_models.h"
#endif
#if ENABLE_WAKEWORD || ENABLE_COMMANDS
#include "model_path.h"
#endif
#if ENABLE_COMMANDS
#include "esp_mn_iface.h"
#include "esp_mn_models.h"
#include "esp_mn_speech_commands.h"
#include "sandy_mqtt.h"
#endif

#if VOICE_AEC_ENABLE
#include "esp_aec.h"
#endif

#include "sandy_wifi.h"
#include "sandy_status.h"
#include "sandy_audio_ctl.h"
#include <math.h>   // sqrt for the per-mic level meters
#if ENABLE_BUZZER
#include "sandy_buzzer.h"
#endif
#if ENABLE_FACE
#include "sandy_face.h"
#endif
#if ENABLE_SERVO
#include "sandy_servo.h"
#endif

// Face states tied to the conversation, all local (no cloud round-trip):
// listening while the session is open, happy while she speaks, idle after.
#if ENABLE_FACE
#define VOICE_FACE(mood) face_set_mood(mood)
// تخبير الوش إذا في جلسة فعلًا. الحارس عنده بيستعمله يقرر إذا تعبير عابر
// (فضول/تركيز/كلام) قاعد أطول من عمره — وساعتها بيرجّعه لحاله.
#define VOICE_SESSION(on) face_set_session_active(on)
#else
#define VOICE_FACE(mood) do {} while (0)
#define VOICE_SESSION(on) do {} while (0)
#endif

#if ENABLE_LED
#include "sandy_led.h"
#define VOICE_LED(st) led_set_state(st)
#else
#define VOICE_LED(st) do {} while (0)
#endif

static const char *TAG = "voice";

static esp_websocket_client_handle_t s_client;
static SemaphoreHandle_t s_ws_mutex;  // guards s_client create/send/destroy
static i2s_chan_handle_t s_rx_chan;   // INMP441 mic
static i2s_chan_handle_t s_tx_chan;   // MAX98357 amp
static StreamBufferHandle_t s_spk_stream;   // server audio waiting to play
static StreamBufferHandle_t s_tx_stream;    // mic audio waiting to go up
static volatile uint32_t s_tx_drop_bytes;   // captured but the uplink was too far behind
static volatile bool s_authed;
static volatile int64_t s_last_rx_audio_ms;  // last time we got Sandy's audio
static volatile bool s_playing;              // true only while actively playing audio

// Playback health counters (cumulative since boot; reported when playback
// stops). dropped > 0 means the jitter buffer overflowed; gap restarts mean
// audible mid-reply dropouts — both point at delivery, not at the I2S side.
static volatile uint32_t s_spk_rx_bytes;     // audio received from the cloud
static volatile uint32_t s_spk_drop_bytes;   // received but didn't fit the buffer
static uint32_t s_spk_play_bytes;            // actually written to the amp
static int s_spk_gaps;                       // playback restarts within 2s

// Barge-in plumbing. flush: dump whatever is buffered and stop playing.
// squelch: drop INCOMING audio briefly too — after a local interrupt the
// server may still be streaming the stale reply's tail. Time-bounded, not
// flag-bounded: Gemini usually finished the turn long before she finishes
// SPEAKING it (it generates faster than realtime), so an "until end_turn"
// squelch would wait for a signal that already passed and eat her NEXT
// reply instead.
static volatile bool s_spk_flush;
static volatile int64_t s_squelch_until_ms;
#define SPK_SQUELCH_MS  1500

// One spare byte so the jitter buffer only ever holds WHOLE 16-bit samples.
// WS fragments split at arbitrary (odd) byte offsets; if an odd byte count
// ever slipped in around a drop or a squelch window, every later sample read
// byte-shifted — that's the static that appears out of nowhere and sticks.
static uint8_t s_rx_carry;
static volatile bool s_rx_has_carry;

#if VOICE_AEC_ENABLE
// Echo canceller: spk_task writes a 16k copy of everything the amp plays into
// s_ref_stream; mic_task pulls it in lockstep and aec_process() strips it from
// the mic signal. With that working, the mic stays OPEN while Sandy talks.
static aec_handle_t *s_aec;
static StreamBufferHandle_t s_ref_stream;     // 16k mono reference (PSRAM)
static int s_aec_chunk;                       // samples per aec_process() call
static int16_t *s_aec_stage;                  // collects mic mono to chunk size
static int s_aec_fill;
static int16_t *s_aec_ref, *s_aec_out;        // aligned per-chunk buffers
static int16_t *s_aec_frame;                  // processed output for one frame
#endif

#if ENABLE_WAKEWORD
// Session is OPEN only between a wake word and the following silence. The WS
// (and so the paid Gemini link) is connected only while it's open.
static volatile bool s_session_active;       // WS up + mic streaming
static volatile bool s_wake_req;             // wake heard; manager should open
static volatile int64_t s_session_voice_ms;  // last user/Sandy activity while open
static volatile int64_t s_link_lost_ms;      // when the WS dropped mid-session, 0 = up
#if ENABLE_COMMANDS
// The command model stays mic_task's property (it is the only toucher of s_mn);
// the session manager only asks. s_mn_want is the request, s_mn_loaded the reply.
static volatile bool s_mn_want = true;       // should the model be resident?
static volatile bool s_mn_loaded;            // mic_task's answer
#endif

static const esp_wn_iface_t *s_wn;
static model_iface_data_t *s_wn_data;
static int s_wn_chunk;                        // samples per detect() call
static int16_t *s_wn_buf;                     // accumulates mic to chunk size
static int s_wn_fill;                         // samples currently in s_wn_buf

static srmodel_list_t *s_models;              // shared esp-sr model list (wake + commands)

#if ENABLE_COMMANDS
// MultiNet: offline "Sandy ..." command words, on the same idle mic audio as
// the wake spotter. A hit either fires a room action over MQTT or opens the
// cloud voice session (see the SANDY_COMMANDS table further down).
static const esp_mn_iface_t *s_mn;
static model_iface_data_t *s_mn_data;
static int s_mn_chunk;
static int16_t *s_mn_buf;
static int s_mn_fill;
#endif

// Pre-roll: mic audio captured between the wake word and auth_ok. The WSS
// handshake takes ~1.2s and people ask their question in the same breath as
// the wake word — without this, those words never reach Gemini and Sandy
// stays silent. Flushed (in order) before the first live frame. When full,
// the OLDEST audio is kept — the question, not the trailing room noise.
static StreamBufferHandle_t s_preroll;
#define PREROLL_BYTES   (96 * 1024)   // 3 s at 16 kHz / 16-bit
#else
static const bool s_session_active = true;    // no gate: always streaming
#endif

// ~100 ms frames at 16 kHz keep WebSocket overhead low without adding latency.
#define MIC_FRAME_SAMPLES   1600

// Below this much contiguous internal RAM, a failed open is out of memory rather
// than off the network — the difference decides what her face says.
//
// 20000 was a guess and it was wrong: a session opened cleanly with the largest
// free block at 6144, which means the TLS task takes its buffers from PSRAM
// (CONFIG_MBEDTLS_EXTERNAL_MEM_ALLOC) and needs far less contiguous internal
// memory than assumed. A threshold set above what actually works turns a network
// problem into a memory accusation, and sends whoever reads it looking in the
// wrong place — which is precisely what it did.
//
// 4096 is under every observed success and still catches a genuinely exhausted
// heap. Measured, not guessed: the "before open" log line prints this number on
// every session, so raising or lowering it is an observation away.
#define WS_TASK_MIN_BLOCK   4096

// Uplink buffer. 128 KB of PSRAM ≈ 4 seconds of 16 kHz 16-bit mono, which is
// how long a stall may last before audio starts being dropped. Sized from the
// observed failures: the link stalls for about a second at a time here.
#define TX_STREAM_BYTES        (128 * 1024)
#define TX_CHUNK_BYTES         4096
// Generous on purpose — this runs on its own task, so waiting costs nothing that
// has to stay real-time, and riding out a stall keeps the call alive.
#define TX_SEND_TIMEOUT_MS     4000
// Half the buffer still queued means we are losing the race with real time.
#define TX_BACKLOG_WARN_BYTES  (TX_STREAM_BYTES / 2)
#define SPK_CHUNK_BYTES     1920    // ~40 ms at 24 kHz / 16-bit
// Jitter buffer: hold this much before starting playback so uneven WiFi
// delivery doesn't underrun the I2S and make Sandy's voice stutter.
// 24 kHz · 16-bit = 48000 B/s, so 14400 B ≈ 300 ms — a bigger cushion against
// WiFi delivery jitter keeps playback from underrunning (less stutter).
#define SPK_PREBUF_BYTES    14400
// Output volume = sample × MUL >> SHIFT. 3>>3 = 0.375 of full scale — a notch
// below half: loud enough across the room, no longer harsh up close.
#define SPK_VOL_MUL         3
#define SPK_VOL_SHIFT       3


// Real calendar time. Only the HMAC handshake needs this — the server checks the
// timestamp against its own clock, so it has to be the wall clock.
static int64_t wall_ms(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (int64_t)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

// Every timeout in this file measures a DURATION, and durations must never come
// off the wall clock: SNTP steps it, and one step forward makes an open session
// look hours idle, so the call gets hung up in the middle of a sentence. This
// clock only ever moves forward, at one speed.
static int64_t now_ms(void) {
    return esp_timer_get_time() / 1000;
}

// True once the wall clock is real (post-2023), i.e. SNTP has set it.
static bool clock_is_set(void) {
    return time(NULL) > 1700000000;  // ~2023-11
}

// Block until SNTP sets the clock — the hello timestamp must land inside the
// server's 30s replay window, so connecting with a 1970 clock just gets us
// rejected. Wait up to ~60s; if it never syncs we proceed anyway and rely on
// the websocket's auto-reconnect to retry once the clock catches up.
static void sync_clock(void) {
    esp_sntp_config_t cfg = ESP_NETIF_SNTP_DEFAULT_CONFIG("pool.ntp.org");
    if (esp_netif_sntp_init(&cfg) != ESP_OK) {
        ESP_LOGW(TAG, "sntp init failed");
        return;
    }
    for (int i = 0; i < 60 && !clock_is_set(); i++) {
        esp_netif_sntp_sync_wait(pdMS_TO_TICKS(1000));
    }
    if (clock_is_set()) {
        ESP_LOGI(TAG, "clock synced");
    } else {
        ESP_LOGW(TAG, "clock not synced after wait; hello may be rejected");
    }
}

// Build the HMAC handshake frame into `out`. Returns the string length.
static int build_hello(char *out, size_t out_len) {
    int64_t ts = wall_ms();

    char signed_msg[96];
    int n = snprintf(signed_msg, sizeof(signed_msg), "%s%lld", SANDY_DEVICE_ID, ts);

    unsigned char mac[32];
    const mbedtls_md_info_t *md = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    mbedtls_md_hmac(md,
                    (const unsigned char *)SANDY_WS_HMAC_KEY, strlen(SANDY_WS_HMAC_KEY),
                    (const unsigned char *)signed_msg, n,
                    mac);

    char hex[65];
    for (int i = 0; i < 32; i++) {
        snprintf(hex + i * 2, 3, "%02x", mac[i]);
    }

    return snprintf(out, out_len,
                    "{\"type\":\"hello\",\"device_id\":\"%s\",\"ts\":%lld,\"hmac\":\"%s\"}",
                    SANDY_DEVICE_ID, ts, hex);
}


// Every step is checked and reported instead of asserted: voice_task already
// has a "voice disabled, carry on" path for a failed audio bring-up, and
// ESP_ERROR_CHECK in here made that path unreachable — a mis-wired mic aborted
// the board instead of leaving the display and the room commands working.
#define I2S_TRY(what, call)                                                    \
    do {                                                                       \
        err = (call);                                                          \
        if (err != ESP_OK) {                                                   \
            ESP_LOGE(TAG, "i2s %s: %s", (what), esp_err_to_name(err));         \
            goto fail;                                                         \
        }                                                                      \
    } while (0)

static esp_err_t i2s_start(void) {
    esp_err_t err;

    // Mic: two INMP441 on I2S_NUM_0, RX only, 32-bit STEREO (one mic per slot).
    // We read both slots — same as the proven sound-direction path — then mix
    // them down to mono for the cloud. Mono mode here read the wrong/empty slot
    // and only picked up a constant noise floor.
    i2s_chan_config_t rx_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_MASTER);
    I2S_TRY("mic channel", i2s_new_channel(&rx_cfg, NULL, &s_rx_chan));
    i2s_std_config_t rx_std = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(VOICE_IN_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_32BIT,
                                                        I2S_SLOT_MODE_STEREO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = PIN_I2S_MIC_SCK,
            .ws   = PIN_I2S_MIC_WS,
            .dout = I2S_GPIO_UNUSED,
            .din  = PIN_I2S_MIC_SD,
            .invert_flags = {0},
        },
    };
    I2S_TRY("mic std mode", i2s_channel_init_std_mode(s_rx_chan, &rx_std));
    I2S_TRY("mic enable", i2s_channel_enable(s_rx_chan));

    // Speaker: MAX98357 on I2S_NUM_1, TX only, 16-bit at 24 kHz (Gemini output).
    i2s_chan_config_t tx_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    // Underrun must play SILENCE. With auto-clear off (the default) the DMA
    // replays its last block over and over on every starved moment — that's a
    // machine-gun trill layered on Sandy's voice, not a clean dropout.
    tx_cfg.auto_clear_after_cb = true;
    // 6 desc × 240 frames ≈ 60 ms at 24 kHz mono. Kept SMALL on purpose: the
    // echo canceller's reference is aligned to this depth, and the depth ramps
    // from zero at each reply start — a small cushion keeps that ramp inside
    // what the adaptive filter can absorb (and makes barge-in cut faster).
    // Delivery jitter is the big PSRAM buffer's job, not the DMA's.
    tx_cfg.dma_frame_num = 240;
    I2S_TRY("amp channel", i2s_new_channel(&tx_cfg, &s_tx_chan, NULL));
    i2s_std_config_t tx_std = {
        .clk_cfg  = I2S_STD_CLK_DEFAULT_CONFIG(VOICE_OUT_RATE),
        .slot_cfg = I2S_STD_PHILIPS_SLOT_DEFAULT_CONFIG(I2S_DATA_BIT_WIDTH_16BIT,
                                                        I2S_SLOT_MODE_MONO),
        .gpio_cfg = {
            .mclk = I2S_GPIO_UNUSED,
            .bclk = PIN_I2S_SPK_BCLK,
            .ws   = PIN_I2S_SPK_LRC,
            .dout = PIN_I2S_SPK_DIN,
            .din  = I2S_GPIO_UNUSED,
            .invert_flags = {0},
        },
    };
    I2S_TRY("amp std mode", i2s_channel_init_std_mode(s_tx_chan, &tx_std));
    // Preload silence so the first DMA cycle doesn't blast whatever happened
    // to be in those buffers — the static heard at the first reply after a
    // power-on.
    {
        static const uint8_t zeros[1440] = {0};
        size_t loaded = 0, w = 0;
        for (int i = 0; i < 8 && i2s_channel_preload_data(s_tx_chan, zeros, sizeof(zeros), &w) == ESP_OK && w > 0; i++) {
            loaded += w;
        }
        (void)loaded;
    }
    I2S_TRY("amp enable", i2s_channel_enable(s_tx_chan));
    return ESP_OK;

fail:
    // Hand both channels back so a later retry (or another owner of the bus)
    // isn't blocked by a half-built one. disable() may complain that a channel
    // was never enabled — harmless, and we're already on the failure path.
    if (s_tx_chan) {
        i2s_channel_disable(s_tx_chan);
        i2s_del_channel(s_tx_chan);
        s_tx_chan = NULL;
    }
    if (s_rx_chan) {
        i2s_channel_disable(s_rx_chan);
        i2s_del_channel(s_rx_chan);
        s_rx_chan = NULL;
    }
    return err;
}
#undef I2S_TRY


// Plain substring check is enough for the small fixed control frames.
static bool text_has(const char *data, int len, const char *needle) {
    static char buf[128];
    int n = len < (int)sizeof(buf) - 1 ? len : (int)sizeof(buf) - 1;
    memcpy(buf, data, n);
    buf[n] = '\0';
    return strstr(buf, needle) != NULL;
}

static void on_ws_event(void *arg, esp_event_base_t base, int32_t id, void *event_data) {
    esp_websocket_event_data_t *ev = (esp_websocket_event_data_t *)event_data;
    switch (id) {
    case WEBSOCKET_EVENT_CONNECTED: {
        char hello[192];
        int n = build_hello(hello, sizeof(hello));
        // ev->client, not s_client: this runs on the WS task, and the session
        // manager may already be swapping s_client for the next session.
        esp_websocket_client_send_text(ev->client, hello, n, portMAX_DELAY);
        ESP_LOGI(TAG, "connected, sent hello");
        break;
    }
    case WEBSOCKET_EVENT_DATA:
        if (ev->op_code == 0x1) {  // text control frame
            if (text_has(ev->data_ptr, ev->data_len, "auth_ok")) {
                s_authed = true;
                s_link_lost_ms = 0;         // back on the air, drop the grace timer
                status_set(SANDY_ST_OK);    // clears any banner from a past failure
                VOICE_FACE(MOOD_FOCUSED);   // she's listening now
                VOICE_LED(LED_STATE_LISTENING);
                ESP_LOGI(TAG, "auth ok, streaming");
            } else if (text_has(ev->data_ptr, ev->data_len, "interrupted")) {
                // Server-side barge-in confirmation: stale audio dies here,
                // whatever comes next belongs to the NEW turn.
                s_spk_flush = true;
                s_squelch_until_ms = 0;
                s_rx_has_carry = false;
                ESP_LOGI(TAG, "interrupted by user (server)");
            } else if (text_has(ev->data_ptr, ev->data_len, "end_turn")) {
                s_squelch_until_ms = 0;   // stale turn fully drained server-side
                ESP_LOGD(TAG, "end of Sandy's turn");
            } else if (text_has(ev->data_ptr, ev->data_len, "auth_fail") ||
                       text_has(ev->data_ptr, ev->data_len, "auth_not_configured") ||
                       text_has(ev->data_ptr, ev->data_len, "bad_handshake") ||
                       text_has(ev->data_ptr, ev->data_len, "replay")) {
                // A configuration problem, not a network one: retrying will not
                // fix a wrong key or a clock outside the replay window, so say
                // so on her face instead of reconnecting forever in silence.
                status_set(SANDY_ST_AUTH_FAILED);
                ESP_LOGE(TAG, "server refused this device — check the key and the clock");
            } else if (text_has(ev->data_ptr, ev->data_len, "error")) {
                ESP_LOGW(TAG, "server error frame");
            }
        } else if (ev->op_code == 0x2 || ev->op_code == 0x0) {  // binary audio (+ continuation)
            if (ev->data_len > 0 && now_ms() >= s_squelch_until_ms) {
                s_last_rx_audio_ms = now_ms();
                const uint8_t *p = (const uint8_t *)ev->data_ptr;
                size_t len = (size_t)ev->data_len;
                s_spk_rx_bytes += len;
                // Re-pair a byte carried from the previous fragment so the
                // buffer only ever sees whole samples.
                if (s_rx_has_carry) {
                    uint8_t pair[2] = { s_rx_carry, p[0] };
                    s_rx_has_carry = false;
                    if (xStreamBufferSpacesAvailable(s_spk_stream) >= 2) {
                        xStreamBufferSend(s_spk_stream, pair, 2, 0);
                    } else {
                        s_spk_drop_bytes += 2;
                    }
                    p++;
                    len--;
                }
                if (len & 1) {           // stash the trailing half-sample
                    s_rx_carry = p[len - 1];
                    s_rx_has_carry = true;
                    len--;
                }
                size_t space = xStreamBufferSpacesAvailable(s_spk_stream) & ~(size_t)1;
                size_t n = len < space ? len : space;
                xStreamBufferSend(s_spk_stream, p, n, 0);
                if (n < len) s_spk_drop_bytes += len - n;
            }
        }
        break;
    case WEBSOCKET_EVENT_DISCONNECTED:
        s_authed = false;
        // A stalled upload (one slow socket write) drops the link mid-sentence.
        // The client reconnects and re-sends hello on its own; note when we lost
        // it so the session manager waits for that instead of hanging up.
        if (s_session_active && !s_link_lost_ms) s_link_lost_ms = now_ms();
        // Two different stories wear the same event. Mid-conversation it is a
        // dropped link and she should say the call died; before ever getting
        // authed it is a server we cannot reach at all. Telling them apart is
        // the difference between "the net cut out" and "check your internet".
        status_set(s_session_active ? SANDY_ST_LINK_DROPPED : SANDY_ST_NO_SERVER);
        ESP_LOGW(TAG, "disconnected");
        break;
    default:
        break;
    }
}


// Drain server audio into the speaker. Runs whether or not we're authed; it just
// idles when there's nothing to play.
static void spk_task(void *arg) {
    uint8_t buf[SPK_CHUNK_BYTES];
    bool playing = false;
    int64_t first_seen = 0;   // when data first appeared while idle
    int64_t last_stop = 0;    // when playback last went idle
    for (;;) {
        // Barge-in: dump everything buffered and go quiet. The ~180ms already
        // inside the I2S DMA plays out, then auto-clear feeds silence.
        if (s_spk_flush) {
            s_spk_flush = false;
            while (xStreamBufferReceive(s_spk_stream, buf, sizeof(buf), 0) > 0) {}
            playing = false;
            s_playing = false;
            first_seen = 0;
            last_stop = now_ms();
            if (s_session_active) {
                VOICE_FACE(MOOD_FOCUSED);
                VOICE_LED(LED_STATE_LISTENING);
            }
        }
        if (!playing) {
            size_t avail = xStreamBufferBytesAvailable(s_spk_stream);
            if (avail == 0) {
                first_seen = 0;
                s_playing = false;
                // ≥ 2 ticks. At FREERTOS_HZ=100 a delay under 10ms rounds to
                // ZERO ticks and this loop busy-spins — at priority 9 on core 1
                // that silently starves the mic task and kills the wake word
                // (IDLE1 watchdog is off in sdkconfig, so nothing ever warned).
                vTaskDelay(pdMS_TO_TICKS(20));
                continue;
            }
            if (first_seen == 0) first_seen = now_ms();
            // Start once we have a cushion — or after 250ms even if it's a short
            // reply, so a small chunk never gets stuck unplayed (which would
            // keep the mic muted forever via half-duplex).
            if (avail >= SPK_PREBUF_BYTES || (now_ms() - first_seen) > 250) {
                playing = true;
                s_playing = true;
                VOICE_FACE(MOOD_HAPPY);     // talking face
                VOICE_LED(LED_STATE_TALKING);
#if VOICE_AEC_ENABLE
                // Fresh playback: pre-fill the reference with silence equal to
                // the TX DMA depth, so the reference lines up with the moment
                // her audio actually leaves the speaker.
                if (s_ref_stream && xStreamBufferIsEmpty(s_ref_stream)) {
                    static const int16_t zeros[320] = {0};   // 20ms pieces
                    for (int ms = 0; ms < VOICE_AEC_REF_DELAY_MS; ms += 20) {
                        xStreamBufferSend(s_ref_stream, zeros, sizeof(zeros), 0);
                    }
                }
#endif
                // Restarting right after a stop = an audible mid-reply gap.
                if (last_stop && (now_ms() - last_stop) < 2000) s_spk_gaps++;
            } else {
                vTaskDelay(pdMS_TO_TICKS(20));  // same zero-tick trap as above
                continue;
            }
        }
        // 300ms tolerance: brief mid-reply WiFi gaps don't re-arm the cushion.
        size_t n = xStreamBufferReceive(s_spk_stream, buf, sizeof(buf), pdMS_TO_TICKS(300));
        if (n) {
#if SPK_VOL_SHIFT
            int16_t *s = (int16_t *)buf;
            for (int i = 0; i < (int)(n / sizeof(int16_t)); i++) {
                s[i] = (int16_t)(((int32_t)s[i] * SPK_VOL_MUL) >> SPK_VOL_SHIFT);
            }
#endif
            // Runtime volume, on top of the compile-time trim above. Applied
            // BEFORE the echo reference is taken, so the canceller sees what the
            // amp will actually play — take it after and every volume change
            // silently breaks echo cancellation.
            {
                int16_t *v = (int16_t *)buf;
                for (int i = 0; i < (int)(n / sizeof(int16_t)); i++) {
                    v[i] = spk_apply(v[i]);
                }
            }
#if VOICE_AEC_ENABLE
            // Echo reference: exactly what the amp will play (post-volume),
            // downsampled 24k -> 16k (2 out of every 3 samples) to match the
            // mic rate. Static buffer — this task is the only writer.
            if (s_ref_stream) {
                static int16_t ref[SPK_CHUNK_BYTES / 3];
                int ns = (int)(n / sizeof(int16_t)), k = 0;
                int16_t *sp = (int16_t *)buf;
                for (int i = 0; i + 2 < ns; i += 3) {
                    ref[k++] = sp[i];
                    ref[k++] = (int16_t)(((int32_t)sp[i + 1] + sp[i + 2]) >> 1);
                }
                xStreamBufferSend(s_ref_stream, ref, k * sizeof(int16_t), 0);
            }
#endif
            size_t written = 0;
            i2s_channel_write(s_tx_chan, buf, n, &written, portMAX_DELAY);
            s_spk_play_bytes += n;
        } else {
            playing = false;
            s_playing = false;
            first_seen = 0;
            last_stop = now_ms();
            // Done talking: back to the listening face while the session is
            // open (the session manager sets idle when it closes).
            if (s_session_active) {
                VOICE_FACE(MOOD_FOCUSED);
                VOICE_LED(LED_STATE_LISTENING);
            }
            // One line per reply: the health of the whole delivery chain.
            // rx≈played & dropped=0 & gaps=0 is a clean run.
            ESP_LOGI(TAG, "playback report: rx=%u played=%u dropped=%u gaps=%d",
                     (unsigned)s_spk_rx_bytes, (unsigned)s_spk_play_bytes,
                     (unsigned)s_spk_drop_bytes, s_spk_gaps);
        }
    }
}

#if ENABLE_WAKEWORD
// Load the WakeNet model packed into the "model" flash partition. Returns false
// if no model is present (caller then falls back to an always-on session).
static bool wakeword_init(void) {
    if (!s_models) s_models = esp_srmodel_init("model");
    srmodel_list_t *models = s_models;
    if (!models || models->num <= 0) {
        ESP_LOGW(TAG, "no models in 'model' partition");
        return false;
    }
    char *name = esp_srmodel_filter(models, ESP_WN_PREFIX, NULL);
    if (!name) {
        ESP_LOGW(TAG, "no wakenet model found");
        return false;
    }
    s_wn = esp_wn_handle_from_name(name);
    s_wn_data = s_wn->create(name, DET_MODE_90);
    s_wn_chunk = s_wn->get_samp_chunksize(s_wn_data);
    s_wn_buf = malloc(s_wn_chunk * sizeof(int16_t));
    s_wn_fill = 0;
    ESP_LOGI(TAG, "wakenet '%s' ready (word='%s', chunk=%d, rate=%d)",
             name, esp_wn_wakeword_from_name(name), s_wn_chunk,
             s_wn->get_samp_rate(s_wn_data));
    return s_wn_buf != NULL;
}

// Feed mono 16-bit PCM in arbitrary lengths; WakeNet needs exact-chunk feeds, so
// we buffer up to s_wn_chunk and detect on each full chunk. Returns true if the
// wake word fired in this call.
static bool wakeword_feed(const int16_t *pcm, int n) {
    if (!s_wn) return false;
    bool hit = false;
    int i = 0;
    while (i < n) {
        int take = s_wn_chunk - s_wn_fill;
        if (take > n - i) take = n - i;
        memcpy(s_wn_buf + s_wn_fill, pcm + i, take * sizeof(int16_t));
        s_wn_fill += take;
        i += take;
        if (s_wn_fill == s_wn_chunk) {
            if (s_wn->detect(s_wn_data, s_wn_buf) == WAKENET_DETECTED) hit = true;
            s_wn_fill = 0;
        }
    }
    return hit;
}
#endif  // ENABLE_WAKEWORD

#if ENABLE_COMMANDS
// ─── Local command words ("Sandy ...") ────────────────────────────────────────
//
// HOW TO ADD OR CHANGE A COMMAND (no model training — just edit the table):
//   1. Get the phoneme string for your phrase (the English model matches sounds,
//      not text). From firmware/brain-core, run:
//          python tools/gen_phonemes.py "SANDY YOUR PHRASE"
//      → prints e.g.  SANDY YOUR PHRASE  ->  "SaNDm Yek Frd"
//   2. Add a row to SANDY_COMMANDS:
//        { id, "SANDY YOUR PHRASE", "<phonemes>", action, "topic", "payload" }
//      • id       : any unique small integer (order doesn't matter).
//      • phrase   : the English text, for logs. Starts with SANDY, 2–4 words.
//                   Keep phrases distinct in SOUND (avoid e.g. LIGHT vs NIGHT).
//      • phonemes : the string from step 1 (this is what's actually matched).
//      • action   : CMD_ROOM   → publishes payload to the MQTT topic (room node)
//                   CMD_ALLOFF → turns light+fan+music off (no topic/payload)
//                   CMD_OPEN   → opens the cloud voice session (free conversation)
//      • topic    : CMD_ROOM only — e.g. room/cmd/light, room/cmd/fan,
//                   room/cmd/music, room/cmd/color, room/cmd/curtain. Else NULL.
//      • payload  : CMD_ROOM only — "on" / "off" / "0".."100". Else NULL.
//   3. Rebuild + flash (OTA is fine now; only the one-time partition resize
//      needed a wired flash).
//   • Keep the list short (a handful). More phrases = more chance of mix-ups.
//   • Raise CMD_DET_THRESHOLD toward 0.9 if it ever fires by accident.

typedef enum { CMD_ROOM, CMD_ALLOFF, CMD_OPEN } cmd_act_t;

typedef struct {
    int          id;
    const char  *phrase;    // English, starts with "SANDY", ALL CAPS (for logs)
    const char  *phonemes;  // ESP-SR phoneme string — generate with tools/gen_phonemes.py
    cmd_act_t    act;
    const char  *topic;     // MQTT topic for CMD_ROOM, else NULL
    const char  *payload;   // MQTT payload for CMD_ROOM, else NULL
} sandy_cmd_t;

static const sandy_cmd_t SANDY_COMMANDS[] = {
    // ── Room control: fully local over MQTT, no cloud ──
    {  1, "SANDY TURN ON THE LIGHT",   "SaNDm TkN nN jc LiT",     CMD_ROOM,   "room/cmd/light", "on"  },
    {  2, "SANDY TURN OFF THE LIGHT",  "SaNDm TkN eF jc LiT",     CMD_ROOM,   "room/cmd/light", "off" },
    {  3, "SANDY TURN ON THE FAN",     "SaNDm TkN nN jc FaN",     CMD_ROOM,   "room/cmd/fan",   "on"  },
    {  4, "SANDY TURN OFF THE FAN",    "SaNDm TkN eF jc FaN",     CMD_ROOM,   "room/cmd/fan",   "off" },
    {  5, "SANDY PLAY MUSIC",          "SaNDm PLd MYoZgK",        CMD_ROOM,   "room/cmd/music", "on"  },
    {  6, "SANDY TURN OFF MUSIC",      "SaNDm TkN eF MYoZgK",     CMD_ROOM,   "room/cmd/music", "off" },
    {  7, "SANDY TURN EVERYTHING OFF", "SaNDm TkN fVRmvgl eF",    CMD_ALLOFF, NULL,             NULL  },  // light+fan+music off

    // ── Need the cloud (focus sessions / spoken answers). For NOW these just
    //    open the voice session so you can talk. TODO phase 2: send an intent
    //    over the voice WS so Sandy does the action / speaks the answer herself.
    {  8, "SANDY WHAT TIME IS IT",     "SaNDm WcT TiM gZ gT",     CMD_OPEN, NULL, NULL },  // → tell the time
    {  9, "SANDY GOOD MORNING",        "SaNDm GwD MeRNgl",        CMD_OPEN, NULL, NULL },  // → morning briefing
    { 10, "SANDY LETS READ",           "SaNDm LfTS RfD",          CMD_OPEN, NULL, NULL },  // → reading focus
    { 11, "SANDY LETS WORK",           "SaNDm LfTS WkK",          CMD_OPEN, NULL, NULL },  // → work focus
    { 12, "SANDY LETS START WORKING",  "SaNDm LfTS STnRT WkKgl",  CMD_OPEN, NULL, NULL },  // → work focus (alt phrasing)
    { 13, "SANDY LETS THINK TOGETHER", "SaNDm LfTS vglK TcGfjk",  CMD_OPEN, NULL, NULL },  // → brainstorm session
    { 14, "SANDY I WANT TO SLEEP",     "SaNDm i WnNT To SLmP",    CMD_OPEN, NULL, NULL },  // → sleep focus
    { 15, "HEY SANDY",                 "hd SaNDm",                CMD_OPEN, NULL, NULL },  // → just start talking to her
};
#define SANDY_COMMANDS_N (sizeof(SANDY_COMMANDS) / sizeof(SANDY_COMMANDS[0]))

#define CMD_TIMEOUT_MS    5760    // window to finish one phrase once speech starts
#define CMD_DET_THRESHOLD 0.50f   // 0..0.9999; raise to reduce false triggers

// Load the English MultiNet model and register the phrases. Returns false (and
// commands stay off) if the model isn't packed in the 'model' partition.
static bool commands_init(void) {
    if (!s_models) s_models = esp_srmodel_init("model");
    if (!s_models) { ESP_LOGW(TAG, "no models for commands"); return false; }
    char *name = esp_srmodel_filter(s_models, ESP_MN_PREFIX, ESP_MN_ENGLISH);
    if (!name) { ESP_LOGW(TAG, "no multinet (en) model packed"); return false; }
    s_mn = esp_mn_handle_from_name(name);
    s_mn_data = s_mn->create(name, CMD_TIMEOUT_MS);
    if (!s_mn_data) { ESP_LOGW(TAG, "multinet create failed"); return false; }
    s_mn->set_det_threshold(s_mn_data, CMD_DET_THRESHOLD);

    esp_mn_commands_alloc(s_mn, s_mn_data);
    for (size_t i = 0; i < SANDY_COMMANDS_N; i++)
        esp_mn_commands_phoneme_add(SANDY_COMMANDS[i].id, SANDY_COMMANDS[i].phrase,
                                    SANDY_COMMANDS[i].phonemes);
    esp_mn_error_t *err = esp_mn_commands_update();
    if (err && err->num)
        ESP_LOGW(TAG, "%d command phrase(s) could not be parsed", err->num);
    s_mn->print_active_speech_commands(s_mn_data);

    s_mn_chunk = s_mn->get_samp_chunksize(s_mn_data);
    s_mn_buf = malloc(s_mn_chunk * sizeof(int16_t));
    s_mn_fill = 0;
    ESP_LOGI(TAG, "multinet '%s' ready (chunk=%d, %d commands)",
             name, s_mn_chunk, (int)SANDY_COMMANDS_N);
    return s_mn_buf != NULL;
}

// Run one recognized command. Returns true if it should OPEN the voice session.
static bool commands_dispatch(int id) {
    for (size_t i = 0; i < SANDY_COMMANDS_N; i++) {
        if (SANDY_COMMANDS[i].id != id) continue;
        const sandy_cmd_t *c = &SANDY_COMMANDS[i];
        ESP_LOGI(TAG, "command: %s", c->phrase);
        switch (c->act) {
        case CMD_OPEN:
            return true;                       // caller opens the voice session
        case CMD_ALLOFF:
#if ENABLE_MQTT
            mqtt_publish_room("room/cmd/light", "off");
            mqtt_publish_room("room/cmd/fan",   "off");
            mqtt_publish_room("room/cmd/music", "off");
#endif
            return false;
        case CMD_ROOM:
        default:
#if ENABLE_MQTT
            mqtt_publish_room(c->topic, c->payload);
#endif
            return false;
        }
    }
    ESP_LOGW(TAG, "command id %d not in table", id);
    return false;
}

// Free the MultiNet model + its buffers, handing its ~70KB of internal SRAM back
// to the system. The command model and the cloud voice link both want that tiny
// internal RAM and it can't hold both — so we unload the model while a session
// is open (they never run at the same time) and commands_init() reloads it once
// the call ends. Runs in mic_task only, so no lock is needed around s_mn.
static void commands_unload(void) {
    if (!s_mn) return;
    esp_mn_commands_free();
    if (s_mn_data) s_mn->destroy(s_mn_data);
    if (s_mn_buf) free(s_mn_buf);
    s_mn = NULL; s_mn_data = NULL; s_mn_buf = NULL; s_mn_fill = 0;
    ESP_LOGI(TAG, "multinet unloaded for the voice session");
}

// Feed idle mic audio; returns true if a command asked to open the voice session.
// Same exact-chunk buffering as wakeword_feed (detect() needs full chunks).
static bool commands_feed(const int16_t *pcm, int n) {
    if (!s_mn || !s_mn_buf) return false;
    bool open = false;
    int i = 0;
    while (i < n) {
        int take = s_mn_chunk - s_mn_fill;
        if (take > n - i) take = n - i;
        memcpy(s_mn_buf + s_mn_fill, pcm + i, take * sizeof(int16_t));
        s_mn_fill += take;
        i += take;
        if (s_mn_fill < s_mn_chunk) continue;
        s_mn_fill = 0;
        esp_mn_state_t st = s_mn->detect(s_mn_data, s_mn_buf);
        if (st == ESP_MN_STATE_DETECTED) {
            esp_mn_results_t *r = s_mn->get_results(s_mn_data);
            if (r && r->num > 0 && commands_dispatch(r->command_id[0])) open = true;
            s_mn->clean(s_mn_data);
        } else if (st == ESP_MN_STATE_TIMEOUT) {
            s_mn->clean(s_mn_data);
        }
    }
    return open;
}
#endif  // ENABLE_COMMANDS

// Queue one chunk of mic audio for the uplink. Never blocks and never touches
// the socket.
//
// It used to write straight to the websocket from the mic loop with a one-second
// patience, and that is what killed conversations on a weak link: the moment the
// uplink stalled for longer than a second, esp_websocket_client declared the
// transport dead ("transport_poll_write(0)"), tore the whole connection down and
// waited five seconds to reconnect — longer than her eight-second listening
// window, so the call was over before it came back. A one-second network hiccup
// should cost a few milliseconds of audio, not the conversation.
//
// So the mic hands audio to a buffer and walks away. ws_tx_task drains it with a
// patience the mic loop could never afford. When the buffer fills — a stall
// longer than the buffer is deep — we drop the NEWEST audio and keep what is
// already queued, because playing her the first half of a sentence in order
// beats a jumbled second half.
static void mic_send(const void *pcm, size_t bytes) {
    if (!s_tx_stream || !s_authed) return;
    size_t room = xStreamBufferSpacesAvailable(s_tx_stream);
    if (room < bytes) {
        s_tx_drop_bytes += bytes;
        return;
    }
    xStreamBufferSend(s_tx_stream, pcm, bytes, 0);
}


// Drains the uplink buffer onto the socket. Its own task, so a slow write blocks
// nothing that has to stay real-time — not the mic, not the wake word, not her
// face.
static void ws_tx_task(void *arg) {
    (void)arg;
    uint8_t *chunk = heap_caps_malloc(TX_CHUNK_BYTES, MALLOC_CAP_SPIRAM);
    if (!chunk) {
        ESP_LOGE(TAG, "uplink buffer alloc failed");
        vTaskDelete(NULL);
        return;
    }
    for (;;) {
        size_t n = xStreamBufferReceive(s_tx_stream, chunk, TX_CHUNK_BYTES,
                                        pdMS_TO_TICKS(100));
        if (n == 0) continue;
        if (xSemaphoreTake(s_ws_mutex, pdMS_TO_TICKS(50)) != pdTRUE) continue;
        if (s_client && s_authed) {
            esp_websocket_client_send_bin(s_client, (const char *)chunk, n,
                                          pdMS_TO_TICKS(TX_SEND_TIMEOUT_MS));
        }
        xSemaphoreGive(s_ws_mutex);

        // A buffer that stays deep means the link cannot keep up with real-time
        // audio. Say so — "slow net" is a different problem from "no net" and
        // the person standing in front of her can act on it.
        size_t queued = xStreamBufferBytesAvailable(s_tx_stream);
        if (queued > TX_BACKLOG_WARN_BYTES) {
            status_set(SANDY_ST_NET_SLOW);
        } else if (s_authed && status_get() == SANDY_ST_NET_SLOW) {
            status_set(SANDY_ST_OK);
        }
    }
}

#if ENABLE_WAKEWORD
// Send whatever was captured while the session was still connecting, before
// the live frame, so the first words arrive in order.
static void preroll_flush(void) {
    if (!s_preroll) return;
    uint8_t tmp[1024];
    size_t n;
    while ((n = xStreamBufferReceive(s_preroll, tmp, sizeof(tmp), 0)) > 0) {
        mic_send(tmp, n);
    }
}
#endif

// Read the mic, convert to 16-bit PCM, and stream it up while Sandy is quiet.
static void mic_task(void *arg) {
    // Stereo read: 2 int32 slots per frame. pcm holds the mono mix.
    int32_t *raw = malloc(MIC_FRAME_SAMPLES * 2 * sizeof(int32_t));
    int16_t *pcm = malloc(MIC_FRAME_SAMPLES * sizeof(int16_t));
    if (!raw || !pcm) {
        ESP_LOGE(TAG, "mic buffers alloc failed");
        vTaskDelete(NULL);
        return;
    }

    // One-pole DC blocker (high-pass): removes the INMP441's constant offset so
    // VAD sees real silence between words. y[n] = x[n] - x[n-1] + R*y[n-1].
    int32_t dc_x1 = 0, dc_y1 = 0;
    int64_t last_diag = 0;
    bool first_frame = true;
    int gate_run = 0;   // consecutive over-gate batches while she talks
#if ENABLE_SERVO
    // Per-mic first-difference energy (diff kills each mic's DC offset).
    // Smoothed over ~400ms; the L/R balance says which side the voice is on.
    int32_t ear_prev_l = 0, ear_prev_r = 0;
    int ear_l = 0, ear_r = 0;
#endif

    for (;;) {
        size_t bytes_read = 0;
        // Bounded wait (not portMAX_DELAY): if I2S ever wedges, the task stays
        // observable instead of vanishing into an infinite block.
        if (i2s_channel_read(s_rx_chan, raw, MIC_FRAME_SAMPLES * 2 * sizeof(int32_t),
                             &bytes_read, pdMS_TO_TICKS(1000)) != ESP_OK) {
            continue;
        }
        if (first_frame) {
            first_frame = false;
            // One-shot "the mic path is alive" marker: if this line is missing
            // from a boot log, I2S RX is delivering nothing — look at wiring or
            // channel config, not at the cloud.
            ESP_LOGI(TAG, "mic up (first frame, %u bytes)", (unsigned)bytes_read);
        }
        int frames = bytes_read / (2 * sizeof(int32_t));

        // INMP441 gives 24-bit data left-justified in a 32-bit slot. Mix the two
        // mics at FULL headroom (>>16 = the top 16 of the 24 data bits — cannot
        // clip, ever), then DC-block. The wanted gain (VOICE_MIC_GAIN_SHIFT) is
        // applied AFTER the echo canceller: applying it here used to saturate
        // her own speaker blasting the mics from a few cm away, and a clipped
        // echo is nonlinear — the AEC cancelled nothing (measured live:
        // residual avg 8000-15000 against a gate of 1500, so the cloud heard
        // her voice as the user and she kept answering herself).
#if ENABLE_SERVO
        int64_t sum_dl = 0, sum_dr = 0;
#endif
        // Snapshot the per-mic controls once per frame, not once per sample: a
        // setting that changes mid-frame would split one 100 ms block between two
        // gains and click. Reading them here also keeps the inner loop branch-free
        // on anything another task can write.
        const int  gain_l  = mic_get_gain(MIC_LEFT);
        const int  gain_r  = mic_get_gain(MIC_RIGHT);
        const bool mute_l  = mic_is_muted(MIC_LEFT);
        const bool mute_r  = mic_is_muted(MIC_RIGHT);
        // Both channels feed the mix; a muted one contributes nothing, so the
        // divisor has to follow or muting one mic would halve the volume of the
        // other instead of isolating it.
        const int  live    = (mute_l ? 0 : 1) + (mute_r ? 0 : 1);
        int64_t sum_sq_l = 0, sum_sq_r = 0;   // per-mic level, for the meters

        for (int i = 0; i < frames; i++) {
            int32_t l = mic_apply(raw[2 * i]     >> 16, gain_l, mute_l);
            int32_t r = mic_apply(raw[2 * i + 1] >> 16, gain_r, mute_r);
            sum_sq_l += (int64_t)l * l;
            sum_sq_r += (int64_t)r * r;
#if ENABLE_SERVO
            // Ears keep the old higher-gain view: they only matter for the wake
            // utterance (she's silent then, no clipping) and the extra bits
            // keep the L/R balance from quantizing away.
            int32_t le = raw[2 * i]     >> VOICE_MIC_GAIN_SHIFT;
            int32_t re = raw[2 * i + 1] >> VOICE_MIC_GAIN_SHIFT;
            sum_dl += (le > ear_prev_l) ? (le - ear_prev_l) : (ear_prev_l - le);
            sum_dr += (re > ear_prev_r) ? (re - ear_prev_r) : (ear_prev_r - re);
            ear_prev_l = le;
            ear_prev_r = re;
#endif
            int32_t x = live ? (l + r) / live : 0;

            int32_t y = x - dc_x1 + (dc_y1 - (dc_y1 >> 6));  // R ≈ 0.984
            dc_x1 = x;
            dc_y1 = y;

            if (y > 32767) y = 32767;
            else if (y < -32768) y = -32768;
            pcm[i] = (int16_t)y;
        }
#if ENABLE_SERVO
        ear_l = (ear_l * 3 + (int)(sum_dl / (frames ? frames : 1))) / 4;
        ear_r = (ear_r * 3 + (int)(sum_dr / (frames ? frames : 1))) / 4;
#endif
        // Strip steady background noise — the fan, the AC — from the mixed mono
        // before anything downstream sees it, so the wake word, the VAD and the
        // cloud all get the same cleaned signal. MIC_FRAME_SAMPLES is 1600, an
        // exact multiple of the suppressor's 160-sample block, so nothing is
        // left over. No-op while the level is off.
        ns_clean(pcm, frames);

        // Per-mic RMS, post-gain and post-mute — so the meter shows what the mix
        // is actually getting, not what the hardware captured. That is the whole
        // point when you are testing one mic at a time: mute the left, speak, and
        // only the right meter should move. If both move, they are cross-wired;
        // if neither does, that mic is dead.
        if (frames > 0) {
            mic_report_levels((int)sqrt((double)(sum_sq_l / frames)),
                              (int)sqrt((double)(sum_sq_r / frames)));
        }

        bool sandy_talking = s_playing ||
                             (now_ms() - s_last_rx_audio_ms) < VOICE_HALF_DUPLEX_TAIL_MS;

        // What downstream (wake word, VAD, cloud) hears: raw mic by default,
        // echo-cancelled when the AEC is up and a session is running.
        int16_t *use = pcm;
#if VOICE_AEC_ENABLE
        if (s_aec && s_session_active) {
            // Chunk the mono mic through the canceller, pulling the speaker
            // reference in lockstep (zeros when she's quiet). Output lands in
            // its own buffer; sample count can differ by < one chunk per loop.
            int out_n = 0;
            for (int i = 0; i < frames; i++) {
                s_aec_stage[s_aec_fill++] = pcm[i];
                if (s_aec_fill == s_aec_chunk) {
                    s_aec_fill = 0;
                    size_t want = (size_t)s_aec_chunk * sizeof(int16_t);
                    size_t got = xStreamBufferReceive(s_ref_stream, s_aec_ref, want, 0);
                    if (got < want) memset((uint8_t *)s_aec_ref + got, 0, want - got);
                    aec_process(s_aec, s_aec_stage, s_aec_ref, s_aec_out);
                    memcpy(s_aec_frame + out_n, s_aec_out, want);
                    out_n += s_aec_chunk;
                }
            }
            if (out_n == 0) continue;   // not a full chunk yet this frame
            use = s_aec_frame;
            frames = out_n;
        }
#if VOICE_AEC_FULL_DUPLEX
        // Full duplex: with the echo gone the mic stays open while she talks.
        bool mic_muted = s_aec ? false : sandy_talking;
#else
        bool mic_muted = sandy_talking;
#endif
#else
        const bool mic_muted = sandy_talking;
#endif

        // Re-apply the intended gain now that the canceller has seen a clean,
        // linear signal (saturating ×16 for the default shift of 12). Everything
        // downstream — wake word, VAD level, duplex gate, what Gemini hears —
        // keeps the exact scale all its thresholds were tuned on. avg doubles
        // as the VAD level and MUST come from the cleaned signal, or her own
        // voice would hold the session open forever now that the mic stays live.
        int64_t sum_abs = 0;
        for (int i = 0; i < frames; i++) {
            int32_t v = (int32_t)use[i] << (16 - VOICE_MIC_GAIN_SHIFT);
            if (v > 32767) v = 32767;
            else if (v < -32768) v = -32768;
            use[i] = (int16_t)v;
            sum_abs += (v < 0) ? -v : v;
        }
        int avg = (int)(sum_abs / (frames ? frames : 1));

#if ENABLE_COMMANDS
        // Hand the command model's internal SRAM to the cloud voice link and
        // take it back when the call ends. The session manager sets s_mn_want;
        // doing the work here keeps s_mn single-owner, so no lock is needed.
        // s_mn_loaded follows the request even when commands_init() fails —
        // otherwise a failed load would retry on every single frame.
        if (s_mn_want != s_mn_loaded) {
            if (s_mn_want) commands_init();
            else           commands_unload();
            s_mn_loaded = s_mn_want;
        }
#endif

#if ENABLE_WAKEWORD
        if (!s_session_active) {
#if VOICE_AEC_ENABLE
            // Stale reference from the closed session would wreck the next
            // one's alignment; this task is the reader, so draining is safe.
            if (s_ref_stream && !xStreamBufferIsEmpty(s_ref_stream)) {
                while (xStreamBufferReceive(s_ref_stream, s_aec_ref,
                                            (size_t)s_aec_chunk * sizeof(int16_t), 0) > 0) {}
                s_aec_fill = 0;
            }
#endif
#if ENABLE_COMMANDS
            // Offline command words on the same idle audio: "Sandy turn on the
            // light" fires a room action over MQTT; an "I need you"-style phrase
            // opens the cloud session just like the wake word does.
            if (!sandy_talking && commands_feed(pcm, frames)) {
                ESP_LOGI(TAG, "command opened a voice session");
                if (s_preroll) xStreamBufferReset(s_preroll);
                s_wake_req = true;
            }
#endif
            // Idle: listen locally for the wake word, stream nothing up. The
            // session manager opens the WS when it sees s_wake_req.
            if (!sandy_talking && wakeword_feed(pcm, frames)) {
                ESP_LOGI(TAG, "wake word detected");
                if (s_preroll) xStreamBufferReset(s_preroll);  // fresh capture
                s_wake_req = true;
                // Local "I heard you" cue — fires on detection, before any cloud
                // connection, so it confirms the wake word independently of the
                // network and the (flaky) remote log.
#if ENABLE_BUZZER
                buzzer_play(MELODY_CURIOUS);
#endif
#if ENABLE_FACE
                face_set_mood(MOOD_CURIOUS);
#endif
#if ENABLE_SERVO
                // Look toward whoever called: the wake utterance is still in
                // the smoothed L/R energies. Two close mics only differ by a
                // few percent, so ±10% imbalance already means full swing
                // (live tests showed bal≈4 for an off-center caller).
                int tot = ear_l + ear_r;
                if (tot > 0) {
                    int bal = ((ear_r - ear_l) * 100) / tot;   // -100 .. +100
                    if (VOICE_EARS_INVERT) bal = -bal;
                    int off = bal * VOICE_EARS_SWING / 10;
                    if (off >  VOICE_EARS_SWING) off =  VOICE_EARS_SWING;
                    if (off < -VOICE_EARS_SWING) off = -VOICE_EARS_SWING;
                    servo_set_angle((uint8_t)(90 + off));
                    ESP_LOGI(TAG, "ears: l=%d r=%d bal=%d -> angle=%d",
                             ear_l, ear_r, bal, 90 + off);
                }
#endif
            }
        } else {
            // Barge-in: the wake-word spotter keeps running while she talks —
            // on the echo-cancelled signal when AEC is up (hears you over her
            // easily), on the raw mic otherwise (works when you're close/loud).
            if (sandy_talking && wakeword_feed(use, frames)) {
                ESP_LOGI(TAG, "barge-in: wake word during playback");
                s_squelch_until_ms = now_ms() + SPK_SQUELCH_MS;  // stale tail only
                s_rx_has_carry = false;
                s_spk_flush = true;
                s_last_rx_audio_ms = 0;   // kill the half-duplex tail now
                s_session_voice_ms = now_ms();
#if ENABLE_BUZZER
                buzzer_play(MELODY_CURIOUS);
#endif
            }
            // Hold the session alive on user speech or Sandy's own audio; the
            // manager closes it once this goes quiet for VOICE_SESSION_IDLE_MS.
            if (avg > VOICE_SESSION_VAD_LEVEL || sandy_talking) {
                s_session_voice_ms = now_ms();
            }
            if (s_authed && !mic_muted) {
                // While she talks, only SUSTAINED real-speech energy opens the
                // stream: a single over-gate batch could be a residual spike of
                // her own echo, VOICE_DUPLEX_GATE_RUN in a row (~100ms) is a
                // human. Pending batches stash in the (idle during playback)
                // preroll, so the interruption's onset still arrives once the
                // run qualifies — nothing of the user's sentence is lost.
                if (!sandy_talking) gate_run = 0;
                if (!sandy_talking || avg > VOICE_DUPLEX_GATE_LEVEL) {
                    if (sandy_talking && ++gate_run < VOICE_DUPLEX_GATE_RUN) {
                        if (s_preroll) {
                            xStreamBufferSend(s_preroll, use,
                                              frames * sizeof(int16_t), 0);
                        }
                    } else {
                        preroll_flush();
                        mic_send(use, frames * sizeof(int16_t));
                    }
                } else if (gate_run) {
                    // The spike died before qualifying — it was echo, not a
                    // voice. Drop the stash with it.
                    gate_run = 0;
                    if (s_preroll) xStreamBufferReset(s_preroll);
                }
            } else if (!s_authed && s_preroll) {
                // Still connecting (or mid-session reconnect): capture instead
                // of dropping, and flush once the link is authed again.
                xStreamBufferSend(s_preroll, use, frames * sizeof(int16_t), 0);
            }
        }
#else
        if (s_authed && !mic_muted) {
            mic_send(use, frames * sizeof(int16_t));
        }
#endif

        int64_t t = now_ms();
        if (t - last_diag > 1500) {
            last_diag = t;
#if ENABLE_WAKEWORD
            ESP_LOGI(TAG, "diag mic=%d session=%d authed=%d talking=%d int=%u psram=%u",
                     avg, (int)s_session_active, (int)s_authed, (int)sandy_talking,
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
#else
            ESP_LOGI(TAG, "diag mic=%d authed=%d playing=%d talking=%d",
                     avg, (int)s_authed, (int)s_playing, (int)sandy_talking);
#endif
        }
    }
}


// One WS client per session: stop()+start() on the same client proved
// unreliable (after the first session closed, the next start never reconnected
// and voice went silent until reboot), so every session gets a fresh init and
// ends with a full destroy. s_ws_mutex keeps mic_send() off a client that is
// being torn down.
static bool ws_open(void) {
    esp_websocket_client_config_t cfg = {
        .uri = SANDY_VOICE_WS_URI,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .buffer_size = 8192,
        // Above LVGL and the housekeeping tasks (default 5), below the audio
        // pair (8/9): TLS decrypt keeps up and audio arrives smoothly instead
        // of in starved bursts.
        .task_prio = 7,
        .reconnect_timeout_ms = 5000,
        .network_timeout_ms = 10000,
    };
    xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    s_client = esp_websocket_client_init(&cfg);
    if (s_client) {
        esp_websocket_register_events(s_client, WEBSOCKET_EVENT_ANY, on_ws_event, NULL);
        if (esp_websocket_client_start(s_client) != ESP_OK) {
            esp_websocket_client_destroy(s_client);
            s_client = NULL;
        }
    }
    bool ok = s_client != NULL;
    xSemaphoreGive(s_ws_mutex);
    if (!ok) ESP_LOGE(TAG, "ws open failed");
    return ok;
}

static void ws_close(void) {
    s_authed = false;
    xSemaphoreTake(s_ws_mutex, portMAX_DELAY);
    if (s_client) {
        esp_websocket_client_stop(s_client);
        esp_websocket_client_destroy(s_client);
        s_client = NULL;
    }
    // Clear again AFTER the teardown: a late auth_ok event can land while
    // stop() is mid-flight and flip the flag back on for good (seen live:
    // authed=1 with no session, for minutes).
    s_authed = false;
    // Whatever is still queued belongs to the call that just ended. Sending it
    // into the next one would open the conversation with the tail of the last.
    if (s_tx_stream) xStreamBufferReset(s_tx_stream);
    if (s_tx_drop_bytes) {
        ESP_LOGW(TAG, "uplink dropped %u bytes this session (link too slow)",
                 (unsigned)s_tx_drop_bytes);
        s_tx_drop_bytes = 0;
    }
    xSemaphoreGive(s_ws_mutex);
}

bool voice_play_local_pcm(const int16_t *pcm, size_t bytes) {
    // Straight into the buffer spk_task already drains, so a locally generated
    // sound travels the identical path as her cloud voice: same buffer, same
    // volume, same amp. A test that used its own channel could pass while the
    // real path was broken, which would make it worse than no test.
    if (!s_spk_stream || !pcm || bytes == 0) return false;
    if (xStreamBufferSpacesAvailable(s_spk_stream) < bytes) return false;
    return xStreamBufferSend(s_spk_stream, pcm, bytes, pdMS_TO_TICKS(200)) == bytes;
}


static void voice_task(void *arg) {
    // Say so while waiting. Boot no longer blocks on Wi-Fi, so with the router
    // down this task is the only thing still waiting — silently, until now, it
    // looked exactly like a robot that had crashed.
    for (int i = 0; !wifi_sandy_is_connected(); i++) {
        // Say it on her face, not just here: "waiting for wifi" in a log nobody
        // is reading is indistinguishable from a robot that has crashed.
        //
        // But not straight away. Associating and then waiting on DHCP takes a
        // couple of seconds on an ordinary boot, and announcing "NO WI-FI" in
        // that window is simply false — it put the banner on her face every
        // single time she started, which teaches the owner to ignore it. Ten
        // half-second passes is five seconds: far longer than a healthy boot,
        // far shorter than a person's patience.
        if (i >= 10) status_set(SANDY_ST_NO_WIFI);
        if (i % 20 == 0) ESP_LOGW(TAG, "waiting for wifi before starting voice");
        vTaskDelay(pdMS_TO_TICKS(500));
    }
    // Wi-Fi is up. Clear the banner now rather than waiting for a successful
    // call: leaving "NO WI-FI" on screen after the router came back is its own
    // kind of lie.
    status_set(SANDY_ST_OK);
    sync_clock();

    if (i2s_start() != ESP_OK) {
        ESP_LOGE(TAG, "I2S init failed, voice disabled");
        vTaskDelete(NULL);
        return;
    }

    // Big buffer in PSRAM so a fast burst of Sandy's reply isn't dropped.
    // 1 MB ≈ 21 s of 24 kHz/16-bit audio: Gemini streams a long reply faster
    // than realtime, and the old 192 KB (~4 s) overflowed on them — the
    // overflow drops chopped whole pieces out of her sentences.
    s_spk_stream = xStreamBufferCreateWithCaps(1024 * 1024, 1, MALLOC_CAP_SPIRAM);
    s_tx_stream  = xStreamBufferCreateWithCaps(TX_STREAM_BYTES, 1, MALLOC_CAP_SPIRAM);
#if ENABLE_WAKEWORD
    s_preroll = xStreamBufferCreateWithCaps(PREROLL_BYTES, 1, MALLOC_CAP_SPIRAM);
#endif
    s_ws_mutex = xSemaphoreCreateMutex();

#if VOICE_AEC_ENABLE
    // Echo canceller: internal RAM first for speed, PSRAM as the fallback.
    // If neither works the voice link still runs — just half-duplex.
    s_ref_stream = xStreamBufferCreateWithCaps(32 * 1024, 1, MALLOC_CAP_SPIRAM);
    aec_config_t acfg = {
        .mic_num = 1, .ref_num = 1, .out_num = 1,
        .filter_length = VOICE_AEC_FILTER_LEN,
        .sample_rate = VOICE_IN_RATE,
        .caps = MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT,
        .mode = AEC_MODE_SR_LOW_COST,
        .nlp_level = AEC_NLP_LEVEL_VERYAGGR,
    };
    ESP_LOGI(TAG, "AEC init (heap_int=%u)...",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
    s_aec = aec_create_from_config(&acfg);
    if (!s_aec) {
        acfg.caps = MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT;
        s_aec = aec_create_from_config(&acfg);
    }
    ESP_LOGI(TAG, "AEC create done (%p)", (void *)s_aec);
    if (s_aec) {
        s_aec_chunk = aec_get_chunksize(s_aec);
        size_t cb = (size_t)s_aec_chunk * sizeof(int16_t);
        s_aec_stage = heap_caps_aligned_alloc(16, cb, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
        s_aec_ref   = heap_caps_aligned_alloc(16, cb, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
        s_aec_out   = heap_caps_aligned_alloc(16, cb, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
        s_aec_frame = heap_caps_malloc((MIC_FRAME_SAMPLES + s_aec_chunk) * sizeof(int16_t),
                                       MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!s_aec_stage || !s_aec_ref || !s_aec_out || !s_aec_frame) {
            ESP_LOGE(TAG, "AEC buffer alloc failed — half-duplex fallback");
            aec_destroy(s_aec);
            s_aec = NULL;
        } else {
            ESP_LOGI(TAG, "AEC up: chunk=%d filter=%d full_duplex=%d",
                     s_aec_chunk, VOICE_AEC_FILTER_LEN, (int)VOICE_AEC_FULL_DUPLEX);
        }
    } else {
        ESP_LOGW(TAG, "AEC create failed — half-duplex fallback");
    }
#endif

#if ENABLE_WAKEWORD
    // BEFORE the audio tasks exist: mic_task feeds the spotter from its very
    // first frame, and a half-initialized WakeNet is a LoadProhibited panic
    // (we lost exactly that race once when AEC init shifted the timing).
    bool wn_ok = wakeword_init();
#endif
#if ENABLE_COMMANDS
    // After wakeword_init: both share s_models (one esp_srmodel_init read).
    bool cmd_ok = commands_init();
    // Tell mic_task the model is already resident, or it would load a second one.
    s_mn_loaded = true;
    ESP_LOGI(TAG, "local command words: %s", cmd_ok ? "ready" : "OFF");
    ESP_LOGW(TAG, "heap after commands: internal_free=%u internal_largest=%u psram_free=%u",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
#endif

    // Pin the audio tasks to core 1 (WiFi/TLS runs on core 0) and give playback
    // the higher priority so Sandy's voice never gets starved → no stutter.
    // Stacks live in internal RAM — if it's exhausted these fail SILENTLY and
    // voice just never answers, so check and shout.
    // Priority 6: below the audio pair (8/9) so capture and playback always win,
    // above the websocket's own task (7) is NOT wanted — this one is allowed to
    // wait, that is its entire job.
    // 3072, not 4096: task stacks come out of internal RAM, and internal RAM is
    // the scarce thing on this board — it is what the TLS task needs to open a
    // voice session at all. This task does one stream read and one send call; it
    // does not go deep.
    if (xTaskCreatePinnedToCore(ws_tx_task, "voice_tx", 3072, NULL, 6, NULL, 1) != pdPASS ||
        xTaskCreatePinnedToCore(spk_task, "voice_spk", 4096, NULL, 9, NULL, 1) != pdPASS ||
        xTaskCreatePinnedToCore(mic_task, "voice_mic", 5120, NULL, 8, NULL, 1) != pdPASS) {
        ESP_LOGE(TAG, "audio task create FAILED (heap_int free=%u largest=%u)",
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
    }

#if ENABLE_WAKEWORD
    if (!wn_ok) {
        // No model packed — fall back to an always-on session so voice still
        // works; just without the cost gate.
        ESP_LOGW(TAG, "wake word unavailable; voice stays always-on");
        s_session_active = true;
        ws_open();
        vTaskDelete(NULL);
        return;
    }

    // Session manager: the paid Gemini link is connected ONLY between a wake
    // word and the silence that follows it.
    for (;;) {
        if (!s_session_active) {
            if (s_wake_req) {
                s_wake_req = false;
                ESP_LOGI(TAG, "opening voice session");
#if ENABLE_COMMANDS
                // Free the command model BEFORE opening, not after the session
                // goes active. The old order deadlocked: its ~70KB of internal
                // SRAM is exactly what the TLS websocket task needs, so the
                // open failed ("Error create websocket task"), the session
                // never went active, and the model was never handed over.
                s_mn_want = false;
                // Wait for the model to actually go, and wait long enough.
                //
                // This used to give up after 500 ms and open anyway. When the
                // unload had not finished, the socket opened against a heap that
                // was still ~70 KB short and failed — and 70 KB is not a margin
                // anything else can make up. The board reported LOW MEMORY on its
                // face, which was true, and pointed at the wrong cause.
                //
                // Three seconds is far beyond how long the release takes when it
                // works, and still shorter than the pause before she answers.
                for (int i = 0; i < 300 && s_mn_loaded; i++) vTaskDelay(pdMS_TO_TICKS(10));
                if (s_mn_loaded) {
                    // Still holding it. Opening now is a guaranteed failure with a
                    // misleading label, so say what actually happened instead.
                    ESP_LOGE(TAG, "command model did not release in 3s — "
                                  "skipping this session rather than failing blind");
                    status_set(SANDY_ST_LOW_MEMORY);
                    s_mn_want = true;
                    continue;
                }
                // Largest contiguous block, not just total free: the TLS task
                // needs one unbroken allocation, and a heap with plenty free and
                // no big block left fails in a way the total never explains.
                ESP_LOGI(TAG, "before open: internal free=%u largest=%u psram=%u",
                         (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                         (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
                         (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
#endif
                if (ws_open()) {
                    s_session_voice_ms = now_ms();
                    s_link_lost_ms = 0;
                    s_session_active = true;
                    VOICE_SESSION(true);
                } else {
                    // The silent freeze lived here. The wake word had already
                    // put MOOD_CURIOUS on her face, and the only code that ever
                    // clears it sits in the close branch below — which needs a
                    // session that opened. So a failed open left her staring,
                    // awake-looking and deaf, until someone power-cycled her.
                    // Now she says which failure it was and goes back to idle.
                    unsigned largest = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
                    ESP_LOGE(TAG, "ws open failed (int free=%u largest=%u)",
                             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                             largest);
                    if (!wifi_sandy_is_connected()) {
                        status_set(SANDY_ST_NO_WIFI);
                    } else if (largest < WS_TASK_MIN_BLOCK) {
                        // The websocket's TLS task needs one contiguous block;
                        // total free being fine while the largest block is not
                        // is exactly how this fails, so report the real reason.
                        status_set(SANDY_ST_LOW_MEMORY);
                    } else {
                        status_set(SANDY_ST_NO_SERVER);
                    }
#if ENABLE_COMMANDS
                    // Nothing to clean up — ws_open destroyed it all — but take
                    // the model back so the offline command words keep working
                    // until the next wake word.
                    s_mn_want = true;
#endif
                }
            }
        } else if (s_link_lost_ms && !s_authed) {
            // Link down mid-call. The mic can't refresh the activity timer while
            // it's down, so without this the idle window expires and we hang up
            // on a conversation the user is still in the middle of. Hold the
            // session open and let the client's auto-reconnect re-auth.
            if ((now_ms() - s_link_lost_ms) < VOICE_RECONNECT_GRACE_MS) {
                s_session_voice_ms = now_ms();
            } else {
                ESP_LOGW(TAG, "link did not come back in %dms, ending session",
                         VOICE_RECONNECT_GRACE_MS);
                s_link_lost_ms = 0;
                s_session_voice_ms = 0;   // fall into the close branch next tick
            }
        } else if ((now_ms() - s_session_voice_ms) > VOICE_SESSION_IDLE_MS && !s_playing) {
            ESP_LOGI(TAG, "session idle, closing");
            s_session_active = false;
            VOICE_SESSION(false);
            s_link_lost_ms = 0;
            ws_close();
#if ENABLE_COMMANDS
            s_mn_want = true;   // the call is over — mic_task reloads the model
#endif
            VOICE_FACE(MOOD_IDLE);
            VOICE_LED(LED_STATE_IDLE);
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
#else
    ws_open();
    vTaskDelete(NULL);  // setup done; the audio tasks carry on
#endif
}

esp_err_t voice_init(void) {
    // 12KB: aec_create_from_config runs on this stack and goes deep.
    xTaskCreate(voice_task, "voice", 12288, NULL, 5, NULL);
    return ESP_OK;
}

bool voice_is_connected(void) {
    return s_authed;
}

bool voice_session_is_active(void) {
#if ENABLE_WAKEWORD
    return s_session_active;
#else
    return s_authed;  // always-on build: connected means in-conversation
#endif
}
