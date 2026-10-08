// Real-time voice link: I2S mic/speaker <-> /voice WebSocket.
// Protocol (matches cloud/app/api/voice_ws/session.py):
//   1. WSS connect, send {"type":"hello","device_id":"...","ts":<unix_ms>,"hmac":"<hex>"[,"kv":2]}
//      hmac = HMAC-SHA256(key, device_id + str(ts)); key = own key ("kv":2) or shared SANDY_WS_HMAC_KEY.
//   2. Wait for {"type":"auth_ok"}.
//   3. Up: PCM 16-bit LE 16 kHz mono. Down: PCM 16-bit LE 24 kHz mono.
//      Control frames: {"type":"end_turn"} / {"type":"error",...}.
//      Up control: {"type":"barge_in"} the moment someone talks over her (she is already silent here).
// Both mics and the speaker reference go through the esp-sr audio front end (echo cancelling,
// the two mics separated into one voice, voice detection, the wake word); only speech goes up.

#include "sandy_voice.h"
#include "config.h"
#include "sandy_identity.h"
#include "sandy_types.h"

#include <ctype.h>
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
#include "esp_netif.h"
#include "esp_netif_sntp.h"
#include "driver/i2s_std.h"
#include "mbedtls/md.h"
#include "mbedtls/platform_util.h"   // zeroize key bytes
#include "nvs.h"
#include "esp_heap_caps.h"

#include "esp_afe_sr_iface.h"
#include "esp_afe_sr_models.h"
#include "esp_afe_config.h"
#include "esp_wn_iface.h"
#include "model_path.h"
#if ENABLE_COMMANDS
#include "esp_mn_iface.h"
#include "esp_mn_models.h"
#include "esp_mn_speech_commands.h"
#endif

// برّا حارس الأوامر: مصافحة الصوت بتسلّم مفتاح الوسيط كمان.
#include "sandy_mqtt.h"


#include "sandy_wifi.h"
#include "sandy_status.h"
#include "sandy_audio_ctl.h"
#include "sandy_net_busy.h"
#include "sandy_health.h"
#include "sandy_echo_probe.h"
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

// Local face states: listening while open, idle after. While she speaks, the face the
// server reads from her words (a `mood` frame; happy until one comes), and after the
// reply the one `end_turn` names, held AFTER_FACE_MS before listening again.
#define AFTER_FACE_MS 2500
#if ENABLE_FACE
#define VOICE_FACE(mood) face_set_mood(mood)
// الحارس بالوش بيرجّع التعبير العابر اللي طوّل أكتر من الجلسة.
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
static volatile uint32_t s_tx_drop_bytes;   // uplink too far behind
static volatile bool s_authed;
static volatile int64_t s_last_rx_audio_ms;  // last time we got Sandy's audio
static volatile bool s_playing;              // true only while actively playing audio
static volatile int  s_out_level;            // 0..100, what the amp plays now (lip sync)

// Playback counters since boot: dropped > 0 = jitter overflow, gaps = mid-reply dropouts.
static volatile uint32_t s_spk_rx_bytes;     // audio received from the cloud
static volatile uint32_t s_spk_drop_bytes;   // received but didn't fit the buffer
static uint32_t s_spk_play_bytes;            // actually written to the amp
static int s_spk_gaps;                       // playback restarts within 2s

// Barge-in: flush dumps the buffer; squelch drops incoming stale audio for a
// fixed time (end_turn usually arrives long before she finishes speaking).
static volatile bool s_spk_flush;
// Her face for this reply, and the one to hold once it has played (MOOD_COUNT: none).
static volatile sandy_mood_t s_talk_mood = MOOD_HAPPY;
static volatile sandy_mood_t s_after_mood = MOOD_COUNT;
static volatile int64_t s_after_until_ms;   // 0: not holding an after-reply face
static volatile int64_t s_squelch_until_ms;
#define SPK_SQUELCH_MS  1500

// Carry an odd byte across WS fragments so the buffer holds only whole samples
// (a shifted stream plays as static).
static uint8_t s_rx_carry;
static volatile bool s_rx_has_carry;

// The audio front end: spk_task writes a 16 kHz copy of what the amp plays (the
// reference); mic_task feeds it with both mics; proc_task reads one clean voice back.
static StreamBufferHandle_t s_ref_stream;     // 16k mono reference (PSRAM)
static const esp_afe_sr_iface_t *s_afe;
static esp_afe_sr_data_t *s_afe_data;
static int s_afe_feed_chunk;                  // samples per channel per feed()
static srmodel_list_t *s_models;              // esp-sr models from the "model" partition
static bool s_wake_ready;                     // a wake word model is running
// Someone talked over her: the uplink task tells the server before the next audio.
static volatile bool s_barge_pending;
#if ENABLE_SERVO
// Per-mic first-difference energy (~400 ms smoothing): which side the caller is on.
static volatile int s_ear_l, s_ear_r;
#endif

// When the WS dropped mid-session (0 = up). Outside the wake-word guard: always written.
static volatile int64_t s_link_lost_ms;

// Server refused this device (key or clock). Latched until the back-off passes,
// instead of retrying every five seconds.
static volatile bool    s_auth_refused;
static volatile int64_t s_auth_refused_at;
#define VOICE_AUTH_BACKOFF_MS  (10 * 60 * 1000)

// Preroll bytes the uplink must not trim as stale (the question said with the wake word).
static volatile uint32_t s_tx_protected;

// Send the preroll as soon as auth_ok arrives, not on the next loud frame.
static volatile bool s_preroll_due;

// Two writers (websocket, local sounds); a stream buffer allows one at a time.
static SemaphoreHandle_t s_spk_wr_lock;

#if ENABLE_WAKEWORD
// The WS (paid link) is up only between a wake word and the following silence.
static volatile bool s_session_active;       // WS up + mic streaming
static volatile bool s_wake_req;             // wake heard; manager should open
static volatile int64_t s_session_voice_ms;  // last user/Sandy activity while open
static int64_t s_session_open_ms;            // when this session opened
#if ENABLE_COMMANDS
// mic_task alone touches s_mn; the session manager only requests.
static volatile bool s_mn_want = true;       // should the model be resident?
static volatile bool s_mn_loaded;            // mic_task's answer
#endif

#if ENABLE_COMMANDS
// MultiNet offline command words, on the idle mic audio (see SANDY_COMMANDS).
static const esp_mn_iface_t *s_mn;
static model_iface_data_t *s_mn_data;
static int s_mn_chunk;
static int16_t *s_mn_buf;
static int s_mn_fill;
#endif

// Pre-roll: audio between wake word and auth_ok (~1.2 s handshake), sent first.
// When full, the OLDEST audio is kept (the question).
static StreamBufferHandle_t s_preroll;
#define PREROLL_BYTES   (96 * 1024)   // 3 s at 16 kHz / 16-bit
#else
static const bool s_session_active = true;    // no gate: always streaming
#endif

// ~100 ms frames at 16 kHz.
#define MIC_FRAME_SAMPLES   1600
// A mic failing this long gets its channel restarted; this many restarts in a row is a fault.
#define MIC_RESTART_AFTER_MS       2000
#define MIC_RESTARTS_BEFORE_FAULT  3
// The amp takes 40 ms chunks into ~60 ms of DMA: a write this late means it is wedged.
#define SPK_WRITE_TIMEOUT_MS       500
#define SPK_FAILS_BEFORE_RESTART   3
// Only the mic's or the amp's own fault is cleared by their recovery.
static volatile bool s_mic_fault, s_spk_fault;

// Below this largest internal block, a failed open is out-of-memory, not network.
// Measured: sessions open fine at 6144 (TLS uses PSRAM); the "before open" log prints it.
#define WS_TASK_MIN_BLOCK   4096

// 128 KB PSRAM ≈ 4 s of uplink audio before drops (link stalls ~1 s here).
#define TX_STREAM_BYTES        (128 * 1024)
#define TX_CHUNK_BYTES         4096
// Own task, so waiting out a stall costs nothing real-time.
#define TX_SEND_TIMEOUT_MS     4000
// Backlog of 2 s: the link isn't keeping up.
#define TX_BACKLOG_WARN_BYTES  (TX_STREAM_BYTES / 2)
// Hysteresis: must fall to 1/8 to clear, or the status flaps mid-sentence.
#define TX_BACKLOG_CLEAR_BYTES (TX_STREAM_BYTES / 8)
// Must stay bad this long before she says anything.
#define TX_BACKLOG_WARN_MS     3000
// Once said, it stands at least this long.
#define TX_BACKLOG_HOLD_MS     5000

// تحت هالرقم الوصلة اللاسلكية ما بتحمل صوت حيّ؛ فوقه السبب إشي تاني.
#define TX_WEAK_RSSI_DBM       (-75)

// سقف التأخير: فوق ثانية (٣٢ كيلو) منرمي الأقدم ومنكمّل من الجديد، وبنطبعه.
// صوت متأخّر تلات ثواني مش محادثة.
#define TX_MAX_LATENCY_BYTES   (32 * 1024)

// بايتات انرمت عشان نلحق الوقت الحقيقي.
static volatile uint32_t s_tx_stale_bytes;

// كم مرّة كان المقبس مشغول (تأخير، مش ضياع). صفر = السبب برّا اللوح.
static volatile uint32_t s_tx_lock_drops;
#define SPK_CHUNK_BYTES     1920    // ~40 ms at 24 kHz / 16-bit
// Adaptive jitter buffer: starts short, grows a step on every audible gap, shrinks
// after a run of clean replies. 24 kHz 16-bit = 48000 B/s: 120 ms min, 480 ms max, 90 ms steps.
#define SPK_PREBUF_MIN      5760
#define SPK_PREBUF_MAX      23040
#define SPK_PREBUF_STEP     4320
// النزول أبطأ من الطلوع بقصد: التقطيع أسوأ من التأخير.
#define SPK_CALM_REPLIES    4

static size_t s_prebuf = SPK_PREBUF_MIN;
static int    s_calm_replies;
// 3>>3 = 0.375 of full scale.
#define SPK_VOL_MUL         3
#define SPK_VOL_SHIFT       3

// Wall clock: only for the HMAC timestamp.
static int64_t wall_ms(void) {
    struct timeval tv;
    gettimeofday(&tv, NULL);
    return (int64_t)tv.tv_sec * 1000 + tv.tv_usec / 1000;
}

// Durations use the monotonic clock: SNTP steps the wall clock.
static int64_t now_ms(void) {
    return esp_timer_get_time() / 1000;
}

// SNTP has set the clock (post-2023).
static bool clock_is_set(void) {
    return time(NULL) > 1700000000;  // ~2023-11
}

// The hello must fall inside the server's 30 s replay window, so no session opens until
// SNTP has set the clock. The router is asked first (it answers on the LAN even when the
// internet is slow), then three public servers. Runs in the background: never blocks.
#define CLOCK_UNSET_SHOW_MS  60000   // after this long unset, she says so
static volatile bool s_clock_bad;    // the server said our time is off: resync first
static volatile bool s_not_paired;   // the server opens no call: no account paired this board
static int64_t s_clock_started_ms;

static void on_clock_sync(struct timeval *tv) {
    (void)tv;
    s_clock_bad = false;
    ESP_LOGI(TAG, "clock synced");
}

static void clock_start(void) {
    static char gw[16];
    esp_netif_ip_info_t ip;
    esp_netif_t *sta = esp_netif_get_handle_from_ifkey("WIFI_STA_DEF");
    if (sta && esp_netif_get_ip_info(sta, &ip) == ESP_OK && ip.gw.addr) {
        esp_ip4addr_ntoa(&ip.gw, gw, sizeof(gw));
    } else {
        snprintf(gw, sizeof(gw), "pool.ntp.org");   // no gateway yet: one public server twice
    }
    esp_sntp_config_t cfg = ESP_NETIF_SNTP_DEFAULT_CONFIG_MULTIPLE(4,
        ESP_SNTP_SERVER_LIST(gw, "time.google.com", "time.cloudflare.com", "pool.ntp.org"));
    cfg.sync_cb = on_clock_sync;
    cfg.wait_for_sync = false;
    if (s_clock_started_ms) esp_netif_sntp_deinit();   // a resync: start over, same servers
    if (esp_netif_sntp_init(&cfg) != ESP_OK) {
        ESP_LOGW(TAG, "sntp init failed");
        return;
    }
    s_clock_started_ms = now_ms();
    ESP_LOGI(TAG, "clock: asking %s, then public servers", gw);
}

// Ready to sign a hello: set, and not refused by the server since the last sync.
static bool clock_ok(void) {
    return clock_is_set() && !s_clock_bad;
}

// ── This board's own voice key ──
// Right after pairing, the server answers a shared-key hello with "device_key";
// it is saved and signs later hellos ("kv":2), after which the shared key is
// refused for this board. "key_unknown" drops it and the board re-enrols.
// Only the voice and websocket tasks touch it, never at once; written once per pairing.
#define DEVKEY_NS  "sandy_vkey"
#define DEVKEY_HEX 64
static char s_dev_key[DEVKEY_HEX + 1];   // hex; "" = use the shared key

static bool is_hex_key(const char *s) {
    if (strlen(s) != DEVKEY_HEX) return false;
    for (int i = 0; i < DEVKEY_HEX; i++) {
        if (!isxdigit((unsigned char)s[i])) return false;
    }
    return true;
}

static void devkey_load(void) {
    s_dev_key[0] = '\0';
    nvs_handle_t h;
    if (nvs_open(DEVKEY_NS, NVS_READONLY, &h) == ESP_OK) {
        size_t n = sizeof(s_dev_key);
        if (nvs_get_str(h, "k", s_dev_key, &n) != ESP_OK || !is_hex_key(s_dev_key)) {
            s_dev_key[0] = '\0';
        }
        nvs_close(h);
    }
    ESP_LOGI(TAG, "voice key: %s", s_dev_key[0] ? "own" : "shared (not enrolled yet)");
}

static void devkey_store(const char *hex) {
    nvs_handle_t h;
    if (nvs_open(DEVKEY_NS, NVS_READWRITE, &h) != ESP_OK) {
        ESP_LOGE(TAG, "voice key: cannot open NVS");
        return;
    }
    esp_err_t e = (hex && *hex) ? nvs_set_str(h, "k", hex) : nvs_erase_key(h, "k");
    if (e == ESP_OK || e == ESP_ERR_NVS_NOT_FOUND) e = nvs_commit(h);
    nvs_close(h);
    if (e != ESP_OK) {
        ESP_LOGE(TAG, "voice key: storing failed (%s)", esp_err_to_name(e));
        return;
    }
    snprintf(s_dev_key, sizeof(s_dev_key), "%s", (hex && *hex) ? hex : "");
    ESP_LOGW(TAG, "voice key: %s", s_dev_key[0] ? "stored this board's own key"
                                                 : "forgotten — will re-enrol");
}

static int hex_nibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    c = (char)tolower((unsigned char)c);
    return (c >= 'a' && c <= 'f') ? c - 'a' + 10 : 0;
}

bool voice_verify_signed(const char *msg, const char *mac_hex) {
    if (!msg || !mac_hex || strlen(mac_hex) != 64) return false;
    for (int i = 0; i < 64; i++) {
        if (!isxdigit((unsigned char)mac_hex[i])) return false;
    }
    unsigned char own[DEVKEY_HEX / 2];
    const unsigned char *key = (const unsigned char *)identity()->hmac_key;
    size_t key_len = strlen(identity()->hmac_key);
    if (s_dev_key[0]) {
        for (int i = 0; i < DEVKEY_HEX / 2; i++) {
            own[i] = (unsigned char)((hex_nibble(s_dev_key[2 * i]) << 4) |
                                     hex_nibble(s_dev_key[2 * i + 1]));
        }
        key = own;
        key_len = sizeof(own);
    }
    if (key_len == 0) return false;

    unsigned char mac[32];
    const int hr = mbedtls_md_hmac(mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), key, key_len,
                                   (const unsigned char *)msg, strlen(msg), mac);
    mbedtls_platform_zeroize(own, sizeof(own));
    if (hr != 0) return false;
    // Constant time: how far a guess matched must not show in how long it took.
    unsigned char diff = 0;
    for (int i = 0; i < 32; i++) {
        const unsigned char want = (unsigned char)((hex_nibble(mac_hex[2 * i]) << 4) |
                                                   hex_nibble(mac_hex[2 * i + 1]));
        diff |= mac[i] ^ want;
    }
    mbedtls_platform_zeroize(mac, sizeof(mac));
    return diff == 0;
}

// Returns the length, or -1 if it doesn't fit (never send a truncated frame).
static int build_hello(char *out, size_t out_len) {
    int64_t ts = wall_ms();

    char signed_msg[96];
    int n = snprintf(signed_msg, sizeof(signed_msg), "%s%lld", identity()->device_id, ts);
    if (n <= 0 || n >= (int)sizeof(signed_msg)) return -1;

    // HMAC key is the raw bytes behind the issued hex.
    unsigned char own[DEVKEY_HEX / 2];
    const unsigned char *key = (const unsigned char *)identity()->hmac_key;
    size_t key_len = strlen(identity()->hmac_key);
    const bool use_own = s_dev_key[0] != '\0';
    if (use_own) {
        for (int i = 0; i < DEVKEY_HEX / 2; i++) {
            own[i] = (unsigned char)((hex_nibble(s_dev_key[2 * i]) << 4) |
                                     hex_nibble(s_dev_key[2 * i + 1]));
        }
        key = own;
        key_len = sizeof(own);
    }

    unsigned char mac[32];
    const mbedtls_md_info_t *md = mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    const int hr = mbedtls_md_hmac(md, key, key_len,
                                   (const unsigned char *)signed_msg, n, mac);
    // Don't leave key bytes on the stack (crash dumps land in flash).
    mbedtls_platform_zeroize(own, sizeof(own));
    if (hr != 0) return -1;

    char hex[65];
    for (int i = 0; i < 32; i++) {
        snprintf(hex + i * 2, 3, "%02x", mac[i]);
    }
    mbedtls_platform_zeroize(mac, sizeof(mac));

    int len = snprintf(out, out_len,
                       "{\"type\":\"hello\",\"device_id\":\"%s\",\"ts\":%lld,\"hmac\":\"%s\"%s}",
                       identity()->device_id, ts, hex, use_own ? ",\"kv\":2" : "");
    return (len > 0 && len < (int)out_len) ? len : -1;
}

// Checked, not asserted: a mis-wired mic must disable voice, not abort the board.
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

    // Mic: two INMP441 on I2S_NUM_0, RX, 32-bit STEREO (one per slot), mixed to mono.
    // Mono mode read the empty slot.
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

    // Speaker: MAX98357 on I2S_NUM_1, TX, 16-bit 24 kHz.
    i2s_chan_config_t tx_cfg = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_1, I2S_ROLE_MASTER);
    // Underrun plays silence, not a repeat of the last DMA block.
    tx_cfg.auto_clear_after_cb = true;
    // ~60 ms DMA, kept small: the AEC reference is aligned to this depth. Jitter is PSRAM's job.
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
    // Preload silence so the first DMA cycle isn't stale buffer contents.
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
    // Release both channels so a retry isn't blocked; disable() may warn, harmless.
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

// Substring check over the whole control message (not NUL-terminated).
static bool text_has(const char *data, int len, const char *needle) {
    const int n = (int)strlen(needle);
    for (int i = 0; i + n <= len; i++) {
        if (!memcmp(data + i, needle, n)) return true;
    }
    return false;
}

// A control message, assembled from its pieces before it is read: the server may split
// it into frames (continuations) or the client into events. PSRAM, from voice_task.
#define RX_TEXT_MAX 2048
static char *s_rx_text;
static int   s_rx_text_len;
static bool  s_rx_text_over;     // longer than RX_TEXT_MAX: dropped whole
static uint8_t s_rx_op;          // 0x1 text or 0x2 audio: what a continuation continues

// قيمة نصّية من إطار تحكّم، بالإيد بلا محلّل JSON.
// بتقرا الإطار كله (بعكس `text_has`): مفتاح الوسيط بيجي بآخر المصافحة.
static bool json_str_field(const char *data, int len, const char *key,
                           char *out, size_t cap) {
    if (!data || len <= 0 || cap == 0) return false;
    out[0] = '\0';

    // منقبل `"key":"x"` و`"key": "x"` (الخادم بيحط فراغ).
    char pat[24];
    int pn = snprintf(pat, sizeof(pat), "\"%s\":", key);
    if (pn <= 0 || pn >= (int)sizeof(pat)) return false;

    // الإطار مش منتهي بصفر بالضرورة.
    const char *end = data + len;
    const char *p = NULL;
    for (int i = 0; i + pn <= len; i++) {
        if (!memcmp(data + i, pat, pn)) { p = data + i + pn; break; }
    }
    if (!p) return false;

    while (p < end && (*p == ' ' || *p == '\t' || *p == '\n' || *p == '\r')) p++;
    if (p >= end || *p != '"') return false;   // مش قيمة نصّية
    p++;

    size_t j = 0;
    while (p < end && *p != '"' && j + 1 < cap) {
        if (*p == '\\' && p + 1 < end) p++;   // \" و \\ بيمرّوا كما هنّ
        out[j++] = *p++;
    }
    // اقتباس ناقص = إطار مقصوص؛ ما منحفظ نص قيمة.
    if (p >= end || *p != '"') return false;
    out[j] = '\0';
    return j > 0;
}

// The mood a server frame names, when the face can show it.
static bool frame_mood(const char *msg, int len, sandy_mood_t *out) {
#if ENABLE_FACE
    char name[16];
    return json_str_field(msg, len, "mood", name, sizeof(name)) && face_mood_by_name(name, out);
#else
    (void)msg; (void)len; (void)out;
    return false;
#endif
}

// One whole control message from the server.
static void on_ws_text(const char *msg, int len) {
    if (text_has(msg, len, "auth_ok")) {
        s_authed = true;
        s_auth_refused = false;
        s_preroll_due = true;       // the words said while we were connecting
        s_link_lost_ms = 0;         // back on the air, drop the grace timer
        status_set(SANDY_PART_LINK, SANDY_ST_OK);   // clears the link's past failure
        status_set(SANDY_PART_IDENTITY, SANDY_ST_OK);   // paired since the last "not_paired"
        VOICE_FACE(MOOD_FOCUSED);   // she's listening now
        VOICE_LED(LED_STATE_LISTENING);
        ESP_LOGI(TAG, "auth ok, streaming");

        // مفتاح الوسيط الخاص بيوصل هون لأنّ المسار موثّق بالتوقيع مش بمفتاح الوسيط،
        // فبيضل شغّال بعد إلغاء المشترك.
#if ENABLE_MQTT
        {
            char bu[65], bp[129];
            if (json_str_field(msg, len, "user", bu, sizeof(bu)) &&
                json_str_field(msg, len, "pass", bp, sizeof(bp))) {
                if (mqtt_sandy_set_credentials(bu, bp))
                    ESP_LOGW(TAG, "got this board's own broker credential — trying it");
            }
        }
#endif
        {
            char dk[DEVKEY_HEX + 8];
            if (json_str_field(msg, len, "device_key", dk, sizeof(dk)) &&
                is_hex_key(dk) && strcmp(dk, s_dev_key) != 0) {
                devkey_store(dk);
            }
        }
    } else if (text_has(msg, len, "interrupted")) {
        // Server confirmed barge-in: drop stale audio.
        s_spk_flush = true;
        s_squelch_until_ms = 0;
        s_rx_has_carry = false;
        s_talk_mood = MOOD_HAPPY;   // the reply that set it is gone
        s_after_mood = MOOD_COUNT;
        ESP_LOGI(TAG, "interrupted by user (server)");
    } else if (text_has(msg, len, "end_turn")) {
        s_squelch_until_ms = 0;   // stale turn fully drained server-side
        // It usually comes long before her audio ends, so the face waits for playback to
        // finish; when nothing is left to play, it shows now.
        sandy_mood_t mood = MOOD_HAPPY;
        if (frame_mood(msg, len, &mood)) {
            if (!s_playing && xStreamBufferIsEmpty(s_spk_stream)) {
                VOICE_FACE(mood);
                s_after_until_ms = now_ms() + AFTER_FACE_MS;
            } else {
                s_after_mood = mood;
            }
        }
        ESP_LOGD(TAG, "end of Sandy's turn");
    } else if (text_has(msg, len, "\"mood\"")) {
        // What she is saying now: talk with that face (end_turn, also carrying a mood, is above).
        sandy_mood_t mood = MOOD_HAPPY;
        if (frame_mood(msg, len, &mood)) {
            s_talk_mood = mood;
            if (s_playing) VOICE_FACE(mood);
        }
    } else if (text_has(msg, len, "key_unknown")) {
        // Key revoked or unknown: re-enrol with the shared key next session.
        devkey_store(NULL);
    } else if (text_has(msg, len, "not_paired")) {
        // No account owns this board yet: the call ends here and she answers locally.
        s_not_paired = true;
        status_set(SANDY_PART_IDENTITY, SANDY_ST_NOT_PAIRED);
        ESP_LOGW(TAG, "server opens no call: this board is not paired — pair it in the app");
    } else if (text_has(msg, len, "replay")) {
        // Our time is off, not our key: resync and try again, no ten-minute lockout.
        s_clock_bad = true;
        status_set(SANDY_PART_CLOCK, SANDY_ST_NO_CLOCK);
        ESP_LOGE(TAG, "server says our clock is off — resyncing before the next session");
    } else if (text_has(msg, len, "auth_fail") ||
               text_has(msg, len, "auth_not_configured") ||
               text_has(msg, len, "bad_handshake")) {
        // Config problem (the key): show it instead of reconnecting forever.
        status_set(SANDY_PART_LINK, SANDY_ST_AUTH_FAILED);
        s_auth_refused = true;
        s_auth_refused_at = now_ms();
        ESP_LOGE(TAG, "server refused this device — check the key "
                      "(no new session for %d min)", VOICE_AUTH_BACKOFF_MS / 60000);
    } else if (text_has(msg, len, "error")) {
        ESP_LOGW(TAG, "server error frame");
    }
}

static void on_ws_event(void *arg, esp_event_base_t base, int32_t id, void *event_data) {
    esp_websocket_event_data_t *ev = (esp_websocket_event_data_t *)event_data;
    switch (id) {
    case WEBSOCKET_EVENT_CONNECTED: {
        char hello[224];
        int n = build_hello(hello, sizeof(hello));
        if (n <= 0) {
            ESP_LOGE(TAG, "hello does not fit — check the device id");
            break;
        }
        // ev->client: s_client may already be the next session's. Bounded wait so a
        // stalled socket can't freeze the WS task.
        if (esp_websocket_client_send_text(ev->client, hello, n, pdMS_TO_TICKS(3000)) < 0) {
            ESP_LOGE(TAG, "hello could not be sent — the client will reconnect");
        } else {
            ESP_LOGI(TAG, "connected, sent hello");
        }
        break;
    }
    case WEBSOCKET_EVENT_DATA:
        // A new frame says what it is; a continuation (0x0) continues the last one.
        if ((ev->op_code == 0x1 || ev->op_code == 0x2) && ev->payload_offset == 0) {
            s_rx_op = ev->op_code;
            if (s_rx_op == 0x1) { s_rx_text_len = 0; s_rx_text_over = false; }
        } else if (ev->op_code != 0x0 && ev->op_code != 0x1 && ev->op_code != 0x2) {
            break;                 // ping, pong, close: not ours to read
        }
        if (s_rx_op == 0x1) {      // a control message, possibly in pieces
            if (!s_rx_text) break;
            if (s_rx_text_len + ev->data_len > RX_TEXT_MAX) s_rx_text_over = true;
            if (!s_rx_text_over && ev->data_len > 0) {
                memcpy(s_rx_text + s_rx_text_len, ev->data_ptr, ev->data_len);
                s_rx_text_len += ev->data_len;
            }
            const bool last_piece = ev->fin &&
                                    ev->payload_offset + ev->data_len >= ev->payload_len;
            if (!last_piece) break;
            s_rx_op = 0;
            if (s_rx_text_over) ESP_LOGW(TAG, "control message over %d bytes dropped", RX_TEXT_MAX);
            else on_ws_text(s_rx_text, s_rx_text_len);
        } else if (s_rx_op == 0x2) {  // audio, a frame or its continuation
            if (ev->data_len > 0 && now_ms() >= s_squelch_until_ms &&
                xSemaphoreTake(s_spk_wr_lock, pdMS_TO_TICKS(50)) == pdTRUE) {
                s_last_rx_audio_ms = now_ms();
                const uint8_t *p = (const uint8_t *)ev->data_ptr;
                size_t len = (size_t)ev->data_len;
                s_spk_rx_bytes += len;
                // Re-pair the byte carried from the previous fragment.
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
                xSemaphoreGive(s_spk_wr_lock);
            } else if (ev->data_len > 0 && now_ms() >= s_squelch_until_ms) {
                // A local sound held the buffer: drop and count this fragment rather than wait.
                s_spk_drop_bytes += (uint32_t)ev->data_len;
            }
        }
        break;
    case WEBSOCKET_EVENT_DISCONNECTED:
        s_authed = false;
        // Stalled upload dropped the link; the client reconnects itself, so the
        // session manager waits instead of hanging up.
        if (s_session_active && !s_link_lost_ms) s_link_lost_ms = now_ms();
        // Mid-conversation: dropped link. Before auth: server unreachable.
        status_set(SANDY_PART_LINK, s_session_active ? SANDY_ST_LINK_DROPPED : SANDY_ST_NO_SERVER);
        ESP_LOGW(TAG, "disconnected");
        break;
    default:
        break;
    }
}

// Drain server audio into the speaker; idles when there's nothing to play.
static void spk_task(void *arg) {
    uint8_t buf[SPK_CHUNK_BYTES];
    bool playing = false;
    int64_t first_seen = 0;   // when data first appeared while idle
    int64_t last_stop = 0;    // when playback last went idle
    int spk_fails = 0;        // amp writes in a row that did not finish
    health_watch();
    for (;;) {
        health_feed();
        // Barge-in: dump the buffer; the DMA tail plays out, then silence.
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
                // The after-reply face has been held long enough: back to listening.
                if (s_after_until_ms && now_ms() >= s_after_until_ms) {
                    s_after_until_ms = 0;
                    if (s_session_active) VOICE_FACE(MOOD_FOCUSED);
                }
                // ≥ 2 ticks: under 10 ms rounds to 0 at 100 Hz and busy-spins, starving the mic task.
                vTaskDelay(pdMS_TO_TICKS(20));
                continue;
            }
            if (first_seen == 0) first_seen = now_ms();
            // Start once cushioned, or after 250 ms so a short reply never sticks (half-duplex would stay muted).
            if (avail >= s_prebuf || (now_ms() - first_seen) > 250) {
                playing = true;
                s_playing = true;
                s_after_until_ms = 0;
                VOICE_FACE(s_talk_mood);    // talking face
                VOICE_LED(LED_STATE_TALKING);
                // Fresh playback: pre-fill the reference with silence equal to the TX DMA depth.
                if (s_ref_stream && xStreamBufferIsEmpty(s_ref_stream)) {
                    static const int16_t zeros[320] = {0};   // 20ms pieces
                    for (int ms = 0; ms < VOICE_REF_DELAY_MS; ms += 20) {
                        xStreamBufferSend(s_ref_stream, zeros, sizeof(zeros), 0);
                    }
                }
                // Restart right after a stop = audible mid-reply gap.
                if (last_stop && (now_ms() - last_stop) < 2000) {
                    s_spk_gaps++;
                    // انقطعت بنص الرد: بنكبّر المخزن فورًا.
                    s_calm_replies = 0;
                    if (s_prebuf < SPK_PREBUF_MAX) {
                        s_prebuf += SPK_PREBUF_STEP;
                        if (s_prebuf > SPK_PREBUF_MAX) s_prebuf = SPK_PREBUF_MAX;
                        ESP_LOGI(TAG, "jitter buffer up to %u ms",
                                 (unsigned)(s_prebuf / 48));
                    }
                } else if (s_prebuf > SPK_PREBUF_MIN
                           && ++s_calm_replies >= SPK_CALM_REPLIES) {
                    s_calm_replies = 0;
                    s_prebuf -= SPK_PREBUF_STEP;
                    if (s_prebuf < SPK_PREBUF_MIN) s_prebuf = SPK_PREBUF_MIN;
                    ESP_LOGI(TAG, "jitter buffer down to %u ms",
                             (unsigned)(s_prebuf / 48));
                }
            } else {
                vTaskDelay(pdMS_TO_TICKS(20));  // same zero-tick trap as above
                continue;
            }
        }
        // 300 ms tolerance so brief gaps don't re-arm the cushion.
        size_t n = xStreamBufferReceive(s_spk_stream, buf, sizeof(buf), pdMS_TO_TICKS(300));
        if (n) {
#if SPK_VOL_SHIFT
            int16_t *s = (int16_t *)buf;
            for (int i = 0; i < (int)(n / sizeof(int16_t)); i++) {
                s[i] = (int16_t)(((int32_t)s[i] * SPK_VOL_MUL) >> SPK_VOL_SHIFT);
            }
#endif
            // Runtime volume BEFORE taking the echo reference, so the AEC sees what the amp plays.
            {
                int16_t *v = (int16_t *)buf;
                int64_t sum = 0;
                const int ns = (int)(n / sizeof(int16_t));
                for (int i = 0; i < ns; i++) {
                    v[i] = spk_apply(v[i]);
                    sum += v[i] < 0 ? -v[i] : v[i];
                }
                // Mean level of these 40 ms, for the mouth.
                int lvl = ns ? (int)(sum / ns) / 30 : 0;
                s_out_level = lvl > 100 ? 100 : lvl;
            }
            // Echo reference: post-volume, 24k→16k (2 of every 3 samples). Leftover samples
            // wait for the next chunk; dropping them drifted the AEC alignment.
            if (s_ref_stream) {
                static int16_t ref[SPK_CHUNK_BYTES / 3 + 2];
                static int16_t carry[2];
                static int     carried;
                int ns = (int)(n / sizeof(int16_t)), k = 0;
                const int16_t *sp = (const int16_t *)buf;
                int i = 0;
                if (carried) {
                    int16_t g[3];
                    int have = carried;
                    for (int c = 0; c < carried; c++) g[c] = carry[c];
                    while (have < 3 && i < ns) g[have++] = sp[i++];
                    if (have == 3) {
                        ref[k++] = g[0];
                        ref[k++] = (int16_t)(((int32_t)g[1] + g[2]) >> 1);
                        carried = 0;
                    } else {
                        for (int c = 0; c < have; c++) carry[c] = g[c];
                        carried = have;
                    }
                }
                for (; i + 2 < ns; i += 3) {
                    ref[k++] = sp[i];
                    ref[k++] = (int16_t)(((int32_t)sp[i + 1] + sp[i + 2]) >> 1);
                }
                for (; i < ns && carried < 2; i++) carry[carried++] = sp[i];
                if (k) xStreamBufferSend(s_ref_stream, ref, k * sizeof(int16_t), 0);
            }
            size_t written = 0;
            esp_err_t wr = i2s_channel_write(s_tx_chan, buf, n, &written,
                                             pdMS_TO_TICKS(SPK_WRITE_TIMEOUT_MS));
            s_spk_play_bytes += written;
            if (wr == ESP_OK && written == n) {
                if (spk_fails) {
                    spk_fails = 0;
                    if (s_spk_fault) {
                        s_spk_fault = false;
                        status_set(SANDY_PART_VOICE, SANDY_ST_OK);
                    }
                }
            } else if (++spk_fails % SPK_FAILS_BEFORE_RESTART == 0) {
                // The rest of this chunk is lost; a wedged amp channel gets restarted.
                i2s_channel_disable(s_tx_chan);
                esp_err_t en = i2s_channel_enable(s_tx_chan);
                ESP_LOGW(TAG, "speaker write failed (%s, %u of %u bytes) — restarted (%s)",
                         esp_err_to_name(wr), (unsigned)written, (unsigned)n,
                         esp_err_to_name(en));
                if (spk_fails == SPK_FAILS_BEFORE_RESTART * 2 && !s_spk_fault) {
                    s_spk_fault = true;
                    status_set(SANDY_PART_VOICE, SANDY_ST_VOICE_OFF);
                }
            }
        } else {
            playing = false;
            s_playing = false;
            s_out_level = 0;
            first_seen = 0;
            last_stop = now_ms();
            // Done talking: the reply's after face for a moment, else listening, while open.
            if (s_session_active) {
                if (s_after_mood < MOOD_COUNT) {
                    VOICE_FACE(s_after_mood);
                    s_after_until_ms = now_ms() + AFTER_FACE_MS;
                } else {
                    VOICE_FACE(MOOD_FOCUSED);
                }
                VOICE_LED(LED_STATE_LISTENING);
            }
            s_after_mood = MOOD_COUNT;
            s_talk_mood = MOOD_HAPPY;
            // Per-reply health: rx≈played, dropped=0, gaps=0 is clean.
            ESP_LOGI(TAG, "playback report: rx=%u played=%u dropped=%u gaps=%d",
                     (unsigned)s_spk_rx_bytes, (unsigned)s_spk_play_bytes,
                     (unsigned)s_spk_drop_bytes, s_spk_gaps);
        }
    }
}

// The audio front end (esp-sr AFE), set up once: input "MMR" = left mic, right mic, the
// reference. Echo cancelling, the two mics separated into one voice (BSS), voice activity
// and the wake word run in one pipeline tuned for exactly this chip. False when it cannot
// start (no models, no memory): she stays deaf rather than streaming the room.
static bool afe_init(void) {
    s_models = esp_srmodel_init("model");
    afe_config_t *cfg = afe_config_init("MMR", s_models, AFE_TYPE_SR, AFE_MODE_HIGH_PERF);
    if (!cfg) {
        ESP_LOGE(TAG, "audio front end: no configuration");
        return false;
    }
    cfg->wakenet_init = ENABLE_WAKEWORD && cfg->wakenet_model_name;
    cfg->wakenet_mode = DET_MODE_90;
    // A fixed gain follows it (VOICE_MIC_GAIN_SHIFT): the levels below were tuned on that.
    cfg->agc_init = false;
    cfg->vad_min_noise_ms = VOICE_VAD_END_MS;
    cfg->memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;
    cfg->afe_perferred_core = 1;
    cfg->afe_perferred_priority = 7;
    s_wake_ready = cfg->wakenet_init;
    s_afe = esp_afe_handle_from_config(cfg);
    s_afe_data = s_afe ? s_afe->create_from_config(cfg) : NULL;
#if ENABLE_REMOTE
    afe_config_print(cfg);   // dev: the echo settings in force, for the echo probe's report
#endif
    afe_config_free(cfg);
    if (!s_afe_data) {
        ESP_LOGE(TAG, "audio front end did not start (psram free=%u)",
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
        return false;
    }
    s_afe_feed_chunk = s_afe->get_feed_chunksize(s_afe_data);
    ESP_LOGI(TAG, "audio front end up: %d samples x %d channels, wake word %s",
             s_afe_feed_chunk, s_afe->get_feed_channel_num(s_afe_data),
             s_wake_ready ? "on" : "OFF");
    s_afe->print_pipeline(s_afe_data);
    return true;
}

#if ENABLE_COMMANDS
// ─── Local command words ("Sandy ...") ───
// To add one: get phonemes with `python tools/gen_phonemes.py "SANDY YOUR PHRASE"`
// and add a row { id, phrase, phonemes, action, output, payload }:
//   id: unique small int; phrase: for logs, SANDY + 2–4 words, distinct in sound;
//   action: CMD_ROOM (publish payload to room/<output>), CMD_ALLOFF, CMD_OPEN (voice session);
//   output: bare room output name (not a topic) for CMD_ROOM, else NULL;
//   payload: "on" / "off" / "0".."100" for CMD_ROOM, else NULL.
// Keep the list short; raise CMD_DET_THRESHOLD toward 0.9 on false hits.

typedef enum { CMD_ROOM, CMD_ALLOFF, CMD_OPEN } cmd_act_t;

typedef struct {
    int          id;
    const char  *phrase;    // English, "SANDY ...", ALL CAPS
    const char  *phonemes;  // from tools/gen_phonemes.py
    cmd_act_t    act;
    const char  *output;    // bare room output for CMD_ROOM, else NULL
    const char  *payload;   // MQTT payload for CMD_ROOM, else NULL
} sandy_cmd_t;

static const sandy_cmd_t SANDY_COMMANDS[] = {
    // ── Room control: local over MQTT ──
    {  1, "SANDY TURN ON THE LIGHT",   "SaNDm TkN nN jc LiT",     CMD_ROOM,   "light",   "on"  },
    {  2, "SANDY TURN OFF THE LIGHT",  "SaNDm TkN eF jc LiT",     CMD_ROOM,   "light",   "off" },
    {  3, "SANDY TURN ON THE FAN",     "SaNDm TkN nN jc FaN",     CMD_ROOM,   "fan",     "on"  },
    {  4, "SANDY TURN OFF THE FAN",    "SaNDm TkN eF jc FaN",     CMD_ROOM,   "fan",     "off" },
    {  5, "SANDY PLAY MUSIC",          "SaNDm PLd MYoZgK",        CMD_ROOM,   "music",   "on"  },
    {  6, "SANDY TURN OFF MUSIC",      "SaNDm TkN eF MYoZgK",     CMD_ROOM,   "music",   "off" },
    {  7, "SANDY TURN EVERYTHING OFF", "SaNDm TkN fVRmvgl eF",    CMD_ALLOFF, NULL,      NULL  },  // light+fan+music off

    // ── Need the cloud: for now these just open the voice session ──
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

#define CMD_TIMEOUT_MS    5760    // window to finish a phrase once speech starts
#define CMD_DET_THRESHOLD 0.50f   // 0..0.9999; raise to reduce false triggers

// Forward declaration: commands_init()'s OOM path calls it.
static void commands_unload(void);

// Load English MultiNet and register phrases; false if the model isn't packed.
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
    if (!s_mn_buf) {
        ESP_LOGE(TAG, "no memory for the command buffer — commands off");
        commands_unload();
        return false;
    }
    ESP_LOGI(TAG, "multinet '%s' ready (chunk=%d, %d commands)",
             name, s_mn_chunk, (int)SANDY_COMMANDS_N);
    return s_mn_buf != NULL;
}

// Returns true if it should open the voice session.
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
            mqtt_publish_room("light", "off");
            mqtt_publish_room("fan",   "off");
            mqtt_publish_room("music", "off");
#endif
            return false;
        case CMD_ROOM:
        default:
#if ENABLE_MQTT
            mqtt_publish_room(c->output, c->payload);
#endif
            return false;
        }
    }
    ESP_LOGW(TAG, "command id %d not in table", id);
    return false;
}

// Free MultiNet (~70 KB internal SRAM) while a session is open; commands_init()
// reloads it after. mic_task only, so no lock around s_mn.
static void commands_unload(void) {
    if (!s_mn) return;
    // multinet already freed the phrase list (it takes ownership), so this logs an
    // expected ERROR; silence it so real ERRORs stay visible. The call stays for safety.
    esp_log_level_t prev = esp_log_level_get("MN_COMMAND");
    esp_log_level_set("MN_COMMAND", ESP_LOG_NONE);
    esp_mn_commands_free();
    esp_log_level_set("MN_COMMAND", prev);
    if (s_mn_data) s_mn->destroy(s_mn_data);
    if (s_mn_buf) free(s_mn_buf);
    s_mn = NULL; s_mn_data = NULL; s_mn_buf = NULL; s_mn_fill = 0;
    ESP_LOGI(TAG, "multinet unloaded for the voice session");
}

// MultiNet needs exact chunks: buffer to s_mn_chunk. True if a command opens the session.
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

// Queue mic audio for the uplink; never blocks or touches the socket (a
// blocking write on a weak link made esp_websocket_client drop the whole call).
// When full, drop the NEWEST audio so what is queued stays in order.
static void mic_send(const void *pcm, size_t bytes) {
    if (!s_tx_stream || !s_authed) return;
    size_t room = xStreamBufferSpacesAvailable(s_tx_stream);
    if (room < bytes) {
        s_tx_drop_bytes += bytes;
        return;
    }
    xStreamBufferSend(s_tx_stream, pcm, bytes, 0);
}

// Drains the uplink buffer on its own task, so slow writes block nothing real-time.
static void ws_tx_task(void *arg) {
    (void)arg;
    uint8_t *chunk = heap_caps_malloc(TX_CHUNK_BYTES, MALLOC_CAP_SPIRAM);
    if (!chunk) {
        ESP_LOGE(TAG, "uplink buffer alloc failed");
        status_set(SANDY_PART_VOICE, SANDY_ST_VOICE_OFF);
        vTaskDelete(NULL);
        return;
    }
    health_watch();
    for (;;) {
        health_feed();
        // Lock the socket BEFORE reading: audio read and then not sent is deleted mid-word.
        if (xSemaphoreTake(s_ws_mutex, pdMS_TO_TICKS(100)) != pdTRUE) {
            s_tx_lock_drops++;   // now a delay counter, not a loss counter
            continue;
        }
        // Ask the client (not s_authed) and ask before reading: the socket can be gone
        // before DISCONNECTED arrives, and pushing at it floods the log.
        const bool live = s_client && esp_websocket_client_is_connected(s_client);
        if (s_authed && !live) {
            // Hand it to the grace timer, which waits for the auto-reconnect.
            s_authed = false;
            if (s_session_active && !s_link_lost_ms) s_link_lost_ms = now_ms();
            ESP_LOGW(TAG, "socket gone without a disconnect event — "
                          "holding the session for the reconnect");
        }
        if (!(live && s_authed)) {
            xSemaphoreGive(s_ws_mutex);
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;            // nothing read, so nothing lost
        }

        if (s_barge_pending) {
            // Ahead of the audio: the server stops her reply without waiting to be sure itself.
            s_barge_pending = false;
            static const char barge[] = "{\"type\":\"barge_in\"}";
            esp_websocket_client_send_text(s_client, barge, sizeof(barge) - 1,
                                           pdMS_TO_TICKS(TX_SEND_TIMEOUT_MS));
            health_feed();   // each send may take TX_SEND_TIMEOUT_MS
        }

        // Catch up to real time: drop the oldest past TX_MAX_LATENCY_BYTES, counted and logged.
        size_t queued_now = xStreamBufferBytesAvailable(s_tx_stream);
        while (queued_now > TX_MAX_LATENCY_BYTES + s_tx_protected) {
            size_t drop = xStreamBufferReceive(s_tx_stream, chunk,
                                               TX_CHUNK_BYTES, 0);
            if (drop == 0) break;
            s_tx_stale_bytes += drop;
            queued_now -= drop;
        }

        // Zero timeout inside the lock, so teardown never waits on a silent mic.
        size_t n = xStreamBufferReceive(s_tx_stream, chunk, TX_CHUNK_BYTES, 0);
        if (n) {
            s_tx_protected = s_tx_protected > n ? s_tx_protected - (uint32_t)n : 0;
            if (esp_websocket_client_send_bin(s_client, (const char *)chunk, n,
                                              pdMS_TO_TICKS(TX_SEND_TIMEOUT_MS)) < 0) {
                // Count failed writes.
                s_tx_drop_bytes += n;
                static int64_t s_last_fail_log;
                if (now_ms() - s_last_fail_log > 5000) {
                    s_last_fail_log = now_ms();
                    ESP_LOGW(TAG, "uplink write failed (%u bytes lost so far)",
                             (unsigned)s_tx_drop_bytes);
                }
            }
        }
        xSemaphoreGive(s_ws_mutex);
        if (n == 0) {
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }

        // A persistently deep buffer means the link can't keep up.
        size_t queued = xStreamBufferBytesAvailable(s_tx_stream);
        const int64_t t = now_ms();
        static int64_t s_backlog_since;   // when the queue first went deep
        static int64_t s_warned_at;       // when we last announced it

        if (queued > TX_BACKLOG_WARN_BYTES) {
            if (s_backlog_since == 0) s_backlog_since = t;
            const sandy_status_t link = status_part_get(SANDY_PART_LINK);
            const bool already = (link == SANDY_ST_NET_SLOW || link == SANDY_ST_LINK_STALL);
            if (t - s_backlog_since > TX_BACKLOG_WARN_MS && !already) {
                // Pick the fault by signal strength: "move closer" is wrong advice on a strong link.
                const int rssi = wifi_sandy_rssi();
                const bool weak = (rssi != 0 && rssi < TX_WEAK_RSSI_DBM);
                status_set(SANDY_PART_LINK, weak ? SANDY_ST_NET_SLOW : SANDY_ST_LINK_STALL);
                s_warned_at = t;
                // Log RSSI with the backlog: below ~-75 dBm the radio can't carry real-time audio.
                ESP_LOGW(TAG, "audio backing up: %u bytes queued, rssi=%d dBm "
                              "(%s), socket busy %lu times, %lu bytes dropped "
                              "as stale",
                         (unsigned)queued, rssi, weak ? "weak" : "fine",
                         (unsigned long)s_tx_lock_drops,
                         (unsigned long)s_tx_stale_bytes);
            }
        } else if (queued < TX_BACKLOG_CLEAR_BYTES) {
            s_backlog_since = 0;
            const sandy_status_t link = status_part_get(SANDY_PART_LINK);
            if (s_authed && t - s_warned_at > TX_BACKLOG_HOLD_MS &&
                (link == SANDY_ST_NET_SLOW || link == SANDY_ST_LINK_STALL)) {
                status_set(SANDY_PART_LINK, SANDY_ST_OK);
            }
        }
        // Between thresholds: leave the status alone (hysteresis).
    }
}

#if ENABLE_WAKEWORD
// Internal SRAM after every call vs. the first call: a leak keeps falling,
// fragmentation settles.
static void session_heap_report(void) {
    static uint32_t s_first_free;
    static uint32_t s_sessions;

    uint32_t freeb = (uint32_t)heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    uint32_t large = (uint32_t)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
    s_sessions++;
    if (s_first_free == 0) s_first_free = freeb;

    ESP_LOGI(TAG, "session %u done: internal free=%u largest=%u  (%+d since first)",
             (unsigned)s_sessions, (unsigned)freeb, (unsigned)large,
             (int)freeb - (int)s_first_free);
}
#endif

#if ENABLE_WAKEWORD
// ── Uplink: speech, not the room ──
// The front end says when it is speech; a hangover keeps trailing words and lets the
// server see the quiet that ends the turn.
#define TX_HANGOVER_MS      900

static int64_t s_tx_open_until;

// Send audio captured while connecting before the live frame.
static void preroll_flush(void) {
    if (!s_preroll) return;
    uint8_t tmp[1024];
    size_t n;
    while ((n = xStreamBufferReceive(s_preroll, tmp, sizeof(tmp), 0)) > 0) {
        mic_send(tmp, n);
        s_tx_protected += (uint32_t)n;   // the catch-up rule leaves these alone
    }
}

// Someone talks over her: silence her here at once (no round trip), and tell the server.
static void barge_in(const char *why) {
    ESP_LOGI(TAG, "barge-in: %s", why);
    s_squelch_until_ms = now_ms() + SPK_SQUELCH_MS;  // stale tail only
    s_rx_has_carry = false;
    s_spk_flush = true;
    s_last_rx_audio_ms = 0;   // kill the half-duplex tail now
    s_session_voice_ms = now_ms();
    s_barge_pending = true;
}
#endif

// The front end works at full headroom; this fixed gain (saturating) brings its output
// to the level the thresholds and the server expect. Returns the mean level.
static int apply_gain(const int16_t *in, int16_t *out, int n) {
    int64_t sum_abs = 0;
    for (int i = 0; i < n; i++) {
        int32_t v = (int32_t)in[i] << (16 - VOICE_MIC_GAIN_SHIFT);
        if (v > 32767) v = 32767;
        else if (v < -32768) v = -32768;
        out[i] = (int16_t)v;
        sum_abs += (v < 0) ? -v : v;
    }
    return (int)(sum_abs / (n ? n : 1));
}

// Reads both mics, applies each one's gain and mute, and feeds the front end: left,
// right and the reference (what the amp plays), interleaved, in its chunk size.
static void mic_task(void *arg) {
    // Stereo: 2 int32 slots per frame.
    int32_t *raw = malloc(MIC_FRAME_SAMPLES * 2 * sizeof(int32_t));
    int16_t *feed = malloc((size_t)s_afe_feed_chunk * 3 * sizeof(int16_t));
    int16_t *ref = malloc((size_t)s_afe_feed_chunk * sizeof(int16_t));
    if (!raw || !feed || !ref) {
        // The allocations fail independently; free all (free(NULL) is a no-op).
        free(raw);
        free(feed);
        free(ref);
        ESP_LOGE(TAG, "mic buffers alloc failed");
        status_set(SANDY_PART_VOICE, SANDY_ST_LOW_MEMORY);   // S4.2: no subsystem fails silently
        vTaskDelete(NULL);
        return;
    }
    // One-pole DC blocker per mic: y[n] = x[n] - x[n-1] + R*y[n-1].
    int32_t dcx[2] = {0, 0}, dcy[2] = {0, 0};
    int fill = 0;
    bool first_frame = true;
    int64_t failing_since = 0;   // first failed read of the current run, 0 = reading fine
    int restarts = 0;            // channel restarts without a good read in between
#if ENABLE_SERVO
    int32_t ear_prev_l = 0, ear_prev_r = 0;
#endif

    health_watch();
    for (;;) {
        health_feed();
        size_t bytes_read = 0;
        // Bounded wait so a wedged I2S stays observable.
        esp_err_t rd = i2s_channel_read(s_rx_chan, raw, MIC_FRAME_SAMPLES * 2 * sizeof(int32_t),
                                        &bytes_read, pdMS_TO_TICKS(1000));
        if (rd != ESP_OK) {
            // A timeout already waited; any other error returns at once and would spin.
            if (rd != ESP_ERR_TIMEOUT) vTaskDelay(pdMS_TO_TICKS(10));
            if (!failing_since) {
                failing_since = now_ms();
                ESP_LOGW(TAG, "mic read failed (%s)", esp_err_to_name(rd));
            } else if (now_ms() - failing_since > MIC_RESTART_AFTER_MS) {
                // Still failing: restart the mic channel, and say so once it stays dead.
                failing_since = now_ms();
                i2s_channel_disable(s_rx_chan);
                esp_err_t en = i2s_channel_enable(s_rx_chan);
                ESP_LOGW(TAG, "mic restarted (%s), try %d", esp_err_to_name(en), restarts + 1);
                if (++restarts == MIC_RESTARTS_BEFORE_FAULT) {
                    s_mic_fault = true;
                    status_set(SANDY_PART_VOICE, SANDY_ST_VOICE_OFF);
                }
            }
            continue;
        }
        if (failing_since) {
            ESP_LOGI(TAG, "mic reading again");
            failing_since = 0;
            restarts = 0;
            if (s_mic_fault) {
                s_mic_fault = false;
                status_set(SANDY_PART_VOICE, SANDY_ST_OK);
            }
        }
        if (first_frame) {
            first_frame = false;
            // Missing from a boot log = I2S RX delivers nothing (wiring/config).
            ESP_LOGI(TAG, "mic up (first frame, %u bytes)", (unsigned)bytes_read);
        }
        int frames = bytes_read / (2 * sizeof(int32_t));
        // Snapshot controls once per frame so a change can't split a block.
        const int  gain_l  = mic_get_gain(MIC_LEFT);
        const int  gain_r  = mic_get_gain(MIC_RIGHT);
        const bool mute_l  = mic_is_muted(MIC_LEFT);
        const bool mute_r  = mic_is_muted(MIC_RIGHT);
        int64_t sum_sq_l = 0, sum_sq_r = 0;   // per-mic level, for the meters
#if ENABLE_SERVO
        int64_t sum_dl = 0, sum_dr = 0;
#endif
        for (int i = 0; i < frames; i++) {
            // 24-bit data left-justified in 32-bit slots: >>16 keeps full headroom.
            int32_t in[2] = {
                mic_apply(raw[2 * i]     >> 16, gain_l, mute_l),
                mic_apply(raw[2 * i + 1] >> 16, gain_r, mute_r),
            };
            int16_t ch[2];
            for (int c = 0; c < 2; c++) {
                int32_t y = in[c] - dcx[c] + (dcy[c] - (dcy[c] >> 6));  // R ≈ 0.984
                dcx[c] = in[c];
                dcy[c] = y;
                ch[c] = (int16_t)(y > 32767 ? 32767 : y < -32768 ? -32768 : y);
            }
            sum_sq_l += (int64_t)ch[0] * ch[0];
            sum_sq_r += (int64_t)ch[1] * ch[1];
#if ENABLE_SERVO
            // Ears keep the higher-gain view for L/R resolution (she's silent during the wake word).
            int32_t le = raw[2 * i]     >> VOICE_MIC_GAIN_SHIFT;
            int32_t re = raw[2 * i + 1] >> VOICE_MIC_GAIN_SHIFT;
            sum_dl += (le > ear_prev_l) ? (le - ear_prev_l) : (ear_prev_l - le);
            sum_dr += (re > ear_prev_r) ? (re - ear_prev_r) : (ear_prev_r - re);
            ear_prev_l = le;
            ear_prev_r = re;
#endif
            if (fill == 0) {
                // This chunk's reference: what the amp played, silence when it was quiet.
                size_t want = (size_t)s_afe_feed_chunk * sizeof(int16_t);
                size_t got = s_ref_stream ? xStreamBufferReceive(s_ref_stream, ref, want, 0) : 0;
                if (got < want) memset((uint8_t *)ref + got, 0, want - got);
            }
            feed[3 * fill]     = ch[0];
            feed[3 * fill + 1] = ch[1];
            feed[3 * fill + 2] = ref[fill];
            if (++fill == s_afe_feed_chunk) {
                echo_probe_feed(feed, s_afe_feed_chunk);
                s_afe->feed(s_afe_data, feed);
                fill = 0;
            }
        }
#if ENABLE_SERVO
        s_ear_l = (s_ear_l * 3 + (int)(sum_dl / (frames ? frames : 1))) / 4;
        s_ear_r = (s_ear_r * 3 + (int)(sum_dr / (frames ? frames : 1))) / 4;
#endif
        // Per-mic RMS post-gain/mute, so testing one mic at a time shows the truth.
        if (frames > 0) {
            mic_report_levels((int)sqrt((double)(sum_sq_l / frames)),
                              (int)sqrt((double)(sum_sq_r / frames)));
        }
    }
}

// Reads the front end: one clean voice, whether it is speech, and the wake word. Opens
// the session on the wake word, sends speech up, and while she talks a voice over her
// (her own echo is already removed here) stops her at once.
static void proc_task(void *arg) {
    const int chunk = s_afe->get_fetch_chunksize(s_afe_data);
    int16_t *out = malloc((size_t)chunk * sizeof(int16_t));
    if (!out) {
        ESP_LOGE(TAG, "voice buffer alloc failed");
        status_set(SANDY_PART_VOICE, SANDY_ST_LOW_MEMORY);
        vTaskDelete(NULL);
        return;
    }
    int64_t last_diag = 0;
    int speech_ms = 0;   // how long the current near speech has lasted
    // The last ~1.5 s of levels: the wake word's loudness is taken from it.
    enum { LEVEL_SLOTS = 48 };
    int levels[LEVEL_SLOTS] = {0};
    int level_at = 0;
    int caller_level = 0;              // how loud the caller is (wake word, then their speech)
    int near_level = VOICE_NEAR_MIN;   // VOICE_NEAR_PCT of it

    health_watch();
    for (;;) {
        health_feed();
        // Returns within 2 s even with no audio.
        afe_fetch_result_t *res = s_afe->fetch(s_afe_data);
        if (!res || res->ret_value == ESP_FAIL || !res->data || res->data_size <= 0) {
            // A failing fetch returns at once: yield, or this spins on Wi-Fi's core.
            vTaskDelay(pdMS_TO_TICKS(10));
            continue;
        }
        int frames = res->data_size / (int)sizeof(int16_t);
        if (frames > chunk) frames = chunk;
        const bool wake = res->wakeup_state == WAKENET_DETECTED;
        int avg = apply_gain(res->data, out, frames);
        levels[level_at] = avg;
        level_at = (level_at + 1) % LEVEL_SLOTS;
        if (wake) {
            // How loud the caller is, from the wake word they just said.
            int peak = 0;
            for (int i = 0; i < LEVEL_SLOTS; i++) if (levels[i] > peak) peak = levels[i];
            caller_level = peak;
            near_level = caller_level * VOICE_NEAR_PCT / 100;
            if (near_level < VOICE_NEAR_MIN) near_level = VOICE_NEAR_MIN;
            ESP_LOGI(TAG, "wake level %d -> near bar %d", peak, near_level);
        }
        // Speech, and from the caller: another room's voices stay below the bar.
        const bool vad = res->vad_state == VAD_SPEECH;
        const bool speech = vad && avg >= near_level;
        if (speech && caller_level) {
            // Follow the caller as they move: only their own speech (above the bar) moves it.
            caller_level = (caller_level * 15 + avg) / 16;
            near_level = caller_level * VOICE_NEAR_PCT / 100;
            if (near_level < VOICE_NEAR_MIN) near_level = VOICE_NEAR_MIN;
        }
        if (!vad) speech_ms = 0;
        else if (speech) speech_ms += frames * 1000 / VOICE_IN_RATE;
        const size_t bytes = (size_t)frames * sizeof(int16_t);
        bool sandy_talking = s_playing ||
                             (now_ms() - s_last_rx_audio_ms) < VOICE_HALF_DUPLEX_TAIL_MS;
        const bool probe_talking = sandy_talking;
        bool barged = false;

#if ENABLE_COMMANDS
        // Swap the command model's SRAM with the voice link on request; s_mn stays
        // single-owner. s_mn_loaded follows even on failure, to avoid retrying every frame.
        if (s_mn_want != s_mn_loaded) {
            if (s_mn_want) commands_init();
            else           commands_unload();
            s_mn_loaded = s_mn_want;
        }
#endif

#if ENABLE_WAKEWORD
        if (!s_session_active) {
#if ENABLE_COMMANDS
            // Offline command words on the idle audio.
            if (!sandy_talking && commands_feed(res->data, frames)) {
                ESP_LOGI(TAG, "command opened a voice session");
                if (s_preroll) xStreamBufferReset(s_preroll);
                s_wake_req = true;
            }
#endif
            if (wake) {
                ESP_LOGI(TAG, "wake word detected");
                if (s_preroll) xStreamBufferReset(s_preroll);  // fresh capture
                s_wake_req = true;
                // Local "heard you" cue, independent of the network.
#if ENABLE_BUZZER
                buzzer_play(MELODY_CURIOUS);
#endif
#if ENABLE_FACE
                face_set_mood(MOOD_CURIOUS);
#endif
#if ENABLE_SERVO
                // Turn toward the caller: ±10% L/R imbalance already means full swing.
                int tot = s_ear_l + s_ear_r;
                if (tot > 0) {
                    int bal = ((s_ear_r - s_ear_l) * 100) / tot;   // -100 .. +100
                    if (VOICE_EARS_INVERT) bal = -bal;
                    int off = bal * VOICE_EARS_SWING / 10;
                    if (off >  VOICE_EARS_SWING) off =  VOICE_EARS_SWING;
                    if (off < -VOICE_EARS_SWING) off = -VOICE_EARS_SWING;
                    servo_move_to((uint8_t)(90 + off));
                    ESP_LOGI(TAG, "ears: l=%d r=%d bal=%d -> angle=%d",
                             s_ear_l, s_ear_r, bal, 90 + off);
                }
#endif
            }
        } else {
            if (wake && sandy_talking) {
#if ENABLE_BUZZER
                buzzer_play(MELODY_CURIOUS);
#endif
                barge_in("wake word");
                barged = true;
                sandy_talking = false;
            }
            // Speech or her own audio keeps the session alive.
            if (speech || sandy_talking) s_session_voice_ms = now_ms();
            if (s_authed && s_preroll_due) {
                // auth_ok just arrived: send the preroll now.
                s_preroll_due = false;
                preroll_flush();
            }
            if (!s_authed) {
                // Connecting or reconnecting: capture, flush once authed.
                if (s_preroll) xStreamBufferSend(s_preroll, out, bytes, 0);
            } else if (sandy_talking) {
                // Held until it is clearly a person (VOICE_BARGE_MS), then she stops here and
                // what was held goes up first, so the start of the interruption isn't lost.
                if (!speech) {
                    if (s_preroll) xStreamBufferReset(s_preroll);
                } else {
                    if (s_preroll) xStreamBufferSend(s_preroll, out, bytes, 0);
                    if (speech_ms >= VOICE_BARGE_MS) {
                        barge_in("voice");
                        barged = true;
                        preroll_flush();
                        s_tx_open_until = now_ms() + TX_HANGOVER_MS;
                    }
                }
            } else if (speech || now_ms() < s_tx_open_until) {
                if (speech && now_ms() >= s_tx_open_until && res->vad_cache_size > 0) {
                    // The start of the word the detector needed before it was sure.
                    const int16_t *cache = res->vad_cache;
                    int left = res->vad_cache_size / (int)sizeof(int16_t);
                    while (left > 0) {
                        int n = left < chunk ? left : chunk;
                        apply_gain(cache, out, n);
                        mic_send(out, (size_t)n * sizeof(int16_t));
                        cache += n;
                        left -= n;
                    }
                    apply_gain(res->data, out, frames);
                }
                if (speech) s_tx_open_until = now_ms() + TX_HANGOVER_MS;
                mic_send(out, bytes);
            }
        }
#else
        if (s_authed) mic_send(out, bytes);
#endif
        echo_probe_out(res->data, frames, probe_talking, vad, speech, avg, near_level, barged);

        int64_t t = now_ms();
        if (t - last_diag > 1500) {
            last_diag = t;
            ESP_LOGI(TAG, "diag mic=%d vad=%d near=%d bar=%d session=%d authed=%d talking=%d "
                     "afe_free=%.2f int=%u psram=%u",
                     avg, (int)vad, (int)speech, near_level, (int)s_session_active,
                     (int)s_authed, (int)sandy_talking, res->ringbuff_free_pct,
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
        }
    }
}

// Fresh WS client per session (stop()+start() failed to reconnect); s_ws_mutex
// keeps mic_send() off a client being torn down.
static bool ws_open(void) {
    esp_websocket_client_config_t cfg = {
        .uri = identity()->voice_uri,
        .crt_bundle_attach = esp_crt_bundle_attach,
        .buffer_size = 8192,
        // Above LVGL/housekeeping (5), below the audio pair (8/9).
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
        // Send a close frame so the server ends the paid Gemini session now; bounded.
        if (!esp_websocket_client_is_connected(s_client) ||
            esp_websocket_client_close(s_client, pdMS_TO_TICKS(1500)) != ESP_OK) {
            esp_websocket_client_stop(s_client);
        }
        esp_websocket_client_destroy(s_client);
        s_client = NULL;
    }
    s_tx_protected = 0;
    s_preroll_due = false;
    // Clear again after teardown: a late auth_ok can land during stop().
    s_authed = false;
    // Drop audio queued from the call that just ended.
    if (s_tx_stream) xStreamBufferReset(s_tx_stream);
    if (s_tx_drop_bytes) {
        ESP_LOGW(TAG, "uplink dropped %u bytes this session (link too slow)",
                 (unsigned)s_tx_drop_bytes);
        s_tx_drop_bytes = 0;
    }
    xSemaphoreGive(s_ws_mutex);
}

bool voice_play_local_pcm(const int16_t *pcm, size_t bytes) {
    // Same buffer as the cloud voice, so a local sound proves the real path.
    if (!s_spk_stream || !s_spk_wr_lock || !pcm || bytes == 0) return false;
    if (xSemaphoreTake(s_spk_wr_lock, pdMS_TO_TICKS(200)) != pdTRUE) return false;
    bool ok = xStreamBufferSpacesAvailable(s_spk_stream) >= bytes &&
              xStreamBufferSend(s_spk_stream, pcm, bytes, 0) == bytes;
    xSemaphoreGive(s_spk_wr_lock);
    return ok;
}

#if ENABLE_WAKEWORD
// The one way a session ends. Releases, in order: socket, network claim,
// command model, face.
static void session_end(void) {
    s_session_active = false;
    VOICE_SESSION(false);
    s_link_lost_ms = 0;
    // A close frame plus the client's stop: bounded by its network timeout, not by us.
    health_unwatch();
    ws_close();
    health_watch();
    net_release(NET_OWNER_VOICE);   // socket gone: updates may run again
#if ENABLE_COMMANDS
    s_mn_want = true;   // mic_task reloads the model
#endif
    VOICE_FACE(MOOD_IDLE);
    VOICE_LED(LED_STATE_IDLE);
}
#endif

// From the session manager: the Wi-Fi status after a few seconds without it, and the
// clock started once there is a network.
static void net_tick(void) {
    static int64_t down_since;
    if (wifi_sandy_is_connected()) {
        down_since = 0;
        if (!s_clock_started_ms) clock_start();
        return;
    }
    if (!down_since) down_since = now_ms();
    // After ~5 s: a normal boot's DHCP takes a couple of seconds.
    if (now_ms() - down_since > 5000) {
        status_set(SANDY_PART_NET, wifi_sandy_password_rejected() ? SANDY_ST_WIFI_BAD_PASS
                                                                  : SANDY_ST_NO_WIFI);
    }
}

// From the session manager: resync after a refusal, and say so when it stays unset.
static void clock_tick(void) {
    static bool resyncing;
    if (s_clock_bad && !resyncing && !s_session_active) {
        resyncing = true;
        clock_start();
    }
    if (!s_clock_bad) resyncing = false;
    if (clock_ok()) {
        status_set(SANDY_PART_CLOCK, SANDY_ST_OK);
    } else if (s_clock_started_ms && now_ms() - s_clock_started_ms > CLOCK_UNSET_SHOW_MS) {
        status_set(SANDY_PART_CLOCK, SANDY_ST_NO_CLOCK);
    }
}

static void voice_task(void *arg) {
    // She listens from boot, network or not: a wake word with no Wi-Fi gets a local
    // answer instead of silence. The network is the session manager's to wait for.
    devkey_load();

    if (i2s_start() != ESP_OK) {
        ESP_LOGE(TAG, "I2S init failed, voice disabled");
        status_set(SANDY_PART_VOICE, SANDY_ST_VOICE_OFF);
        vTaskDelete(NULL);
        return;
    }

    // 1 MB PSRAM ≈ 21 s at 24 kHz: Gemini streams faster than realtime (192 KB overflowed).
    s_spk_stream = xStreamBufferCreateWithCaps(1024 * 1024, 1, MALLOC_CAP_SPIRAM);
    s_tx_stream  = xStreamBufferCreateWithCaps(TX_STREAM_BYTES, 1, MALLOC_CAP_SPIRAM);
#if ENABLE_WAKEWORD
    s_preroll = xStreamBufferCreateWithCaps(PREROLL_BYTES, 1, MALLOC_CAP_SPIRAM);
#endif
    s_ws_mutex = xSemaphoreCreateMutex();
    s_spk_wr_lock = xSemaphoreCreateMutex();
    s_rx_text = heap_caps_malloc(RX_TEXT_MAX, MALLOC_CAP_SPIRAM);
    if (!s_spk_stream || !s_tx_stream || !s_ws_mutex || !s_spk_wr_lock || !s_rx_text) {
        ESP_LOGE(TAG, "voice buffers could not be allocated — voice disabled");
        status_set(SANDY_PART_VOICE, SANDY_ST_VOICE_OFF);
        vTaskDelete(NULL);
        return;
    }

    // The reference the front end cancels against (spk_task writes, mic_task reads).
    s_ref_stream = xStreamBufferCreateWithCaps(32 * 1024, 1, MALLOC_CAP_SPIRAM);
    // BEFORE the audio tasks: they read the front end's handle and chunk size.
    if (!s_ref_stream || !afe_init()) {
        ESP_LOGE(TAG, "audio front end unavailable — voice disabled");
        status_set(SANDY_PART_VOICE, SANDY_ST_VOICE_OFF);
        vTaskDelete(NULL);
        return;
    }

#if ENABLE_COMMANDS
    // Shares s_models with the front end.
    bool cmd_ok = commands_init();
    // Already resident, so mic_task doesn't load a second one.
    s_mn_loaded = true;
    ESP_LOGI(TAG, "local command words: %s", cmd_ok ? "ready" : "OFF");
    ESP_LOGW(TAG, "heap after commands: internal_free=%u internal_largest=%u psram_free=%u",
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
             (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
#endif

    // Audio tasks on core 1 (WiFi/TLS on core 0; the front-end reader too), playback highest. Uplink task at 6
    // (may wait), 3 KB stack (internal RAM). Separate checks so the log says which failed.
    int audio_task_fail = 0;
    if (xTaskCreatePinnedToCore(ws_tx_task, "voice_tx", 3072, NULL, 6, NULL, 1) != pdPASS) {
        audio_task_fail++;
        ESP_LOGE(TAG, "audio task voice_tx create FAILED");
    }
    if (xTaskCreatePinnedToCore(spk_task, "voice_spk", 4096, NULL, 9, NULL, 1) != pdPASS) {
        audio_task_fail++;
        ESP_LOGE(TAG, "audio task voice_spk create FAILED");
    }
    if (xTaskCreatePinnedToCore(mic_task, "voice_mic", 5120, NULL, 8, NULL, 1) != pdPASS) {
        audio_task_fail++;
        ESP_LOGE(TAG, "audio task voice_mic create FAILED");
    }
    // The front end's own worker runs on core 1; reading it can wait on core 0.
    if (xTaskCreatePinnedToCore(proc_task, "voice_proc", 6144, NULL, 8, NULL, 0) != pdPASS) {
        audio_task_fail++;
        ESP_LOGE(TAG, "audio task voice_proc create FAILED");
    }
    // She can hear now: booting is over (each part reports its own faults).
    status_set(SANDY_PART_SYSTEM, SANDY_ST_OK);
    if (audio_task_fail) {
        // Out of internal RAM for stacks: say so on her face.
        ESP_LOGE(TAG, "%d of 4 audio tasks did not start (heap_int free=%u largest=%u)",
                 audio_task_fail,
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL));
        status_set(SANDY_PART_VOICE, SANDY_ST_LOW_MEMORY);
    }

#if ENABLE_WAKEWORD
    if (!s_wake_ready) {
        // Fail closed: without a wake word the mic stays local (no always-on streaming).
        // Command words still open a session if loaded.
        ESP_LOGE(TAG, "wake word unavailable — the microphone stays local "
                      "(sessions open only from a command word)");
    }

    // Session manager: the paid link is up only between a wake word and the silence after.
    health_watch();
    for (;;) {
        health_feed();
        net_tick();
        clock_tick();
        if (s_session_active && (s_auth_refused || s_clock_bad || s_not_paired)) {
            // Refused: end now (a clock refusal resyncs; see clock_tick).
            ESP_LOGW(TAG, "closing the session the server refused");
            session_end();
            if (s_not_paired) {
                // Not a fault to back off from: the next wake word asks again, so a
                // pairing in the app takes effect at once.
                s_not_paired = false;
#if ENABLE_BUZZER
                buzzer_play(MELODY_ERROR);
#endif
                VOICE_FACE(MOOD_CONFUSED);
            }
        } else if (!s_session_active && s_wake_req && !identity_complete()) {
            // No server to call and no name to call it with: say so, not "no internet".
            s_wake_req = false;
            ESP_LOGW(TAG, "wake word, but this board is not set up");
            status_set(SANDY_PART_IDENTITY, SANDY_ST_NOT_SET_UP);
#if ENABLE_BUZZER
            buzzer_play(MELODY_ERROR);
#endif
            VOICE_FACE(MOOD_CONFUSED);
            VOICE_LED(LED_STATE_IDLE);
        } else if (!s_session_active && s_wake_req && !wifi_sandy_is_connected()) {
            // Heard, but nowhere to send it: answer here, with a tone and a face.
            s_wake_req = false;
            ESP_LOGW(TAG, "wake word with no Wi-Fi");
            status_set(SANDY_PART_NET, wifi_sandy_password_rejected() ? SANDY_ST_WIFI_BAD_PASS
                                                                      : SANDY_ST_NO_WIFI);
#if ENABLE_BUZZER
            buzzer_play(MELODY_SAD);
#endif
            VOICE_FACE(MOOD_WORRIED);
            VOICE_LED(LED_STATE_IDLE);
        } else if (!s_session_active && s_wake_req && !clock_ok()) {
            // The hello would be refused: say so here instead of opening a doomed call.
            s_wake_req = false;
            ESP_LOGW(TAG, "wake ignored: the clock is not set yet");
            status_set(SANDY_PART_CLOCK, SANDY_ST_NO_CLOCK);
#if ENABLE_BUZZER
            buzzer_play(MELODY_ERROR);
#endif
            VOICE_FACE(MOOD_CONFUSED);
            VOICE_LED(LED_STATE_IDLE);
        } else if (!s_session_active) {
            if (s_wake_req && s_auth_refused &&
                now_ms() - s_auth_refused_at < VOICE_AUTH_BACKOFF_MS) {
                s_wake_req = false;
                ESP_LOGW(TAG, "wake ignored: the server refused this device %d s ago",
                         (int)((now_ms() - s_auth_refused_at) / 1000));
                status_set(SANDY_PART_LINK, SANDY_ST_AUTH_FAILED);
                VOICE_FACE(MOOD_IDLE);
                VOICE_LED(LED_STATE_IDLE);
            } else if (s_wake_req) {
                s_wake_req = false;
                // One TLS session at a time (sandy_net_busy.h): wait out a short manifest fetch,
                // else drop the wake. Held until ws_close.
                for (int i = 0; i < 50 && !net_claim(NET_OWNER_VOICE); i++) {
                    vTaskDelay(pdMS_TO_TICKS(100));
                    health_feed();
                }
                if (net_owner() != NET_OWNER_VOICE) {
                    ESP_LOGW(TAG, "wake ignored: update in progress");
                    VOICE_FACE(MOOD_IDLE);
                    VOICE_LED(LED_STATE_IDLE);
                    continue;
                }
                ESP_LOGI(TAG, "opening voice session");
                s_tx_open_until = 0;
#if ENABLE_COMMANDS
                // Free the command model BEFORE opening: TLS needs its ~70 KB.
                s_mn_want = false;
                // Wait up to 3 s for the model to go; opening while it's resident fails.
                for (int i = 0; i < 300 && s_mn_loaded; i++) vTaskDelay(pdMS_TO_TICKS(10));
                if (s_mn_loaded) {
                    ESP_LOGE(TAG, "command model did not release in 3s — "
                                  "skipping this session rather than failing blind");
                    status_set(SANDY_PART_LINK, SANDY_ST_LOW_MEMORY);
                    s_mn_want = true;
                    net_release(NET_OWNER_VOICE);
                    continue;
                }
                // Largest block matters: TLS needs one contiguous allocation.
                ESP_LOGI(TAG, "before open: internal free=%u largest=%u psram=%u",
                         (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                         (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
                         (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
#endif
                // Waits for the uplink's socket lock (one send, up to 4 s).
                health_unwatch();
                const bool opened = ws_open();
                health_watch();
                if (opened) {
                    s_session_voice_ms = now_ms();
                    s_session_open_ms = now_ms();
                    s_link_lost_ms = 0;
                    s_session_active = true;
                    // المخزن بيرجع لأصغر قيمة مع كل مكالمة، عشان يقيس الشبكة الحالية.
                    s_prebuf = SPK_PREBUF_MIN;
                    s_calm_replies = 0;
                    VOICE_SESSION(true);
                } else {
                    // A failed open must clear the wake face and say why, or she stares, deaf.
                    unsigned largest = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
                    ESP_LOGE(TAG, "ws open failed (int free=%u largest=%u)",
                             (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                             largest);
                    if (!wifi_sandy_is_connected()) {
                        status_set(SANDY_PART_NET, SANDY_ST_NO_WIFI);
                    } else if (largest < WS_TASK_MIN_BLOCK) {
                        // Not enough contiguous internal RAM for TLS.
                        status_set(SANDY_PART_LINK, SANDY_ST_LOW_MEMORY);
                    } else {
                        status_set(SANDY_PART_LINK, SANDY_ST_NO_SERVER);
                    }
                    net_release(NET_OWNER_VOICE);   // ws_open left no socket behind
#if ENABLE_COMMANDS
                    // Take the command model back until the next wake word.
                    s_mn_want = true;
#endif
                }
            }
        } else if (s_link_lost_ms && !s_authed) {
            // Link down mid-call: hold the session within the grace window while the client re-auths.
            if ((now_ms() - s_link_lost_ms) < VOICE_RECONNECT_GRACE_MS) {
                s_session_voice_ms = now_ms();
            } else {
                ESP_LOGW(TAG, "link did not come back in %dms, ending session",
                         VOICE_RECONNECT_GRACE_MS);
                s_link_lost_ms = 0;
                s_session_voice_ms = 0;   // fall into the close branch next tick
            }
        } else if (!s_playing && now_ms() - s_session_open_ms > VOICE_SESSION_MAX_MS) {
            ESP_LOGW(TAG, "session reached its %d min cap, closing", VOICE_SESSION_MAX_MS / 60000);
            session_heap_report();
            session_end();
        } else if (!s_playing &&
                   now_ms() - (s_last_rx_audio_ms > s_session_open_ms ? s_last_rx_audio_ms
                                                                      : s_session_open_ms)
                       > VOICE_NO_REPLY_MS) {
            // Speech keeps a session open, but not talk she never answers.
            ESP_LOGW(TAG, "%d s of talk with no reply from her, closing", VOICE_NO_REPLY_MS / 1000);
            session_heap_report();
            session_end();
        } else if ((now_ms() - s_session_voice_ms) > VOICE_SESSION_IDLE_MS && !s_playing) {
            ESP_LOGI(TAG, "session idle, closing");
            session_heap_report();
            session_end();
        }
        vTaskDelay(pdMS_TO_TICKS(100));
    }
#else
    // Always-on build: the link needs the network and the clock first.
    while (!wifi_sandy_is_connected() || !clock_ok()) {
        net_tick();
        vTaskDelay(pdMS_TO_TICKS(500));
    }
    ws_open();
    vTaskDelete(NULL);  // setup done; the audio tasks carry on
#endif
}

esp_err_t voice_init(void) {
    // 12 KB: aec_create_from_config goes deep.
    xTaskCreate(voice_task, "voice", 12288, NULL, 5, NULL);
    return ESP_OK;
}

int voice_output_level(void) {
    return s_playing ? s_out_level : 0;
}

bool voice_is_connected(void) {
    return s_authed;
}

bool voice_session_is_active(void) {
#if ENABLE_WAKEWORD
    return s_session_active;
#else
    return s_authed;  // always-on build: connected = in conversation
#endif
}
