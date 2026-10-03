// Runtime mic/speaker control (see sandy_audio_ctl.h).

#include "sandy_audio_ctl.h"
#include "config.h"          // VOICE_OUT_RATE
#include "sandy_nvs.h"
#include "sandy_voice.h"

#include <math.h>

#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "nvs.h"
#include "nvs_flash.h"

static const char *TAG = "audio_ctl";
static const char *NVS_NS = "sandy_audio";

// Read by the mic task, written by MQTT. Word-sized and atomic here; no lock, so
// MQTT stays out of the audio path.
static volatile int  s_gain[MIC_COUNT] = { AUDIO_GAIN_UNITY, AUDIO_GAIN_UNITY };
static volatile bool s_muted[MIC_COUNT] = { false, false };
static volatile int  s_level[MIC_COUNT] = { 0, 0 };
static volatile int  s_volume = 100;

static int clamp_gain(int v)
{
    if (v < AUDIO_GAIN_MIN) return AUDIO_GAIN_MIN;
    if (v > AUDIO_GAIN_MAX) return AUDIO_GAIN_MAX;
    return v;
}

// Deferred: a slider drag becomes one flash write (sandy_nvs.h).
static void save_i32(const char *key, int32_t v)
{
    nvs_save_deferred(NVS_NS, key, NVS_VAL_I32, v);
}

static int32_t load_i32(const char *key, int32_t fallback)
{
    nvs_handle_t h;
    if (nvs_open(NVS_NS, NVS_READONLY, &h) != ESP_OK) return fallback;
    int32_t v = fallback;
    if (nvs_get_i32(h, key, &v) != ESP_OK) v = fallback;
    nvs_close(h);
    return v;
}

void audio_ctl_init(void)
{
    s_gain[MIC_LEFT]   = clamp_gain((int)load_i32("gain_l", AUDIO_GAIN_UNITY));
    s_gain[MIC_RIGHT]  = clamp_gain((int)load_i32("gain_r", AUDIO_GAIN_UNITY));
    s_muted[MIC_LEFT]  = load_i32("mute_l", 0) != 0;
    s_muted[MIC_RIGHT] = load_i32("mute_r", 0) != 0;
    s_volume           = (int)load_i32("volume", 100);
    if (s_volume < 0)   s_volume = 0;
    if (s_volume > 100) s_volume = 100;

    // Never boot with both mics muted.
    if (s_muted[MIC_LEFT] && s_muted[MIC_RIGHT]) {
        s_muted[MIC_LEFT] = false;
        save_i32("mute_l", 0);
        ESP_LOGW(TAG, "both mics were saved muted — restored the left one");
    }

    ESP_LOGI(TAG, "gain L=%d R=%d, mute L=%d R=%d, volume=%d",
             s_gain[MIC_LEFT], s_gain[MIC_RIGHT],
             (int)s_muted[MIC_LEFT], (int)s_muted[MIC_RIGHT], s_volume);
}

// ── Microphones ──

void mic_set_gain(sandy_mic_ch_t ch, int percent)
{
    if (ch >= MIC_COUNT) return;
    s_gain[ch] = clamp_gain(percent);
    save_i32(ch == MIC_LEFT ? "gain_l" : "gain_r", s_gain[ch]);
    ESP_LOGI(TAG, "mic %s gain = %d%%", ch == MIC_LEFT ? "L" : "R", s_gain[ch]);
}

int mic_get_gain(sandy_mic_ch_t ch)
{
    return ch < MIC_COUNT ? s_gain[ch] : AUDIO_GAIN_UNITY;
}

bool mic_set_muted(sandy_mic_ch_t ch, bool muted)
{
    if (ch >= MIC_COUNT) return false;
    // Refuse the mute that would leave her deaf.
    if (muted) {
        sandy_mic_ch_t other = (ch == MIC_LEFT) ? MIC_RIGHT : MIC_LEFT;
        if (s_muted[other]) {
            ESP_LOGW(TAG, "refusing to mute both mics");
            return false;
        }
    }
    s_muted[ch] = muted;
    save_i32(ch == MIC_LEFT ? "mute_l" : "mute_r", muted ? 1 : 0);
    ESP_LOGI(TAG, "mic %s %s", ch == MIC_LEFT ? "L" : "R", muted ? "muted" : "live");
    return true;
}

bool mic_is_muted(sandy_mic_ch_t ch)
{
    return ch < MIC_COUNT ? s_muted[ch] : false;
}

int mic_get_level(sandy_mic_ch_t ch)
{
    return ch < MIC_COUNT ? s_level[ch] : 0;
}

void mic_report_levels(int rms_l, int rms_r)
{
    // Reference puts ordinary speech mid-meter.
    const int REF = 3000;
    int l = rms_l * 100 / REF;
    int r = rms_r * 100 / REF;
    if (l > 100) l = 100;
    if (r > 100) r = 100;
    // Fast attack, slow release.
    s_level[MIC_LEFT]  = l > s_level[MIC_LEFT]  ? l : (s_level[MIC_LEFT]  * 3 + l) / 4;
    s_level[MIC_RIGHT] = r > s_level[MIC_RIGHT] ? r : (s_level[MIC_RIGHT] * 3 + r) / 4;
}

// ── Speaker ──

void spk_set_volume(int percent)
{
    if (percent < 0) percent = 0;
    if (percent > 100) percent = 100;
    s_volume = percent;
    save_i32("volume", percent);
    ESP_LOGI(TAG, "volume = %d%%", percent);
}

int spk_get_volume(void)
{
    return s_volume;
}

int16_t spk_apply(int16_t sample)
{
    int v = s_volume;
    if (v >= 100) return sample;
    if (v <= 0) return 0;
    return (int16_t)(((int32_t)sample * v) / 100);
}

// freq=0 is a rest.
static bool spk_tone(int freq, int ms, int amp)
{
    // Must match her 24 kHz buffer, or tones play fast and sharp.
    const int SR = VOICE_OUT_RATE, CH = VOICE_OUT_RATE / 50;   // 20 ms blocks
    const int total = SR * ms / 1000;
    int16_t buf[CH];
    static float phase;                       // continuous across calls, so two
                                              // touching tones do not click
    float inc = 2.0f * (float)M_PI * (float)freq / SR;

    for (int sent = 0; sent < total; sent += CH) {
        for (int i = 0; i < CH; i++) {
            if (freq <= 0) {
                buf[i] = 0;
            } else {
                buf[i] = (int16_t)(amp * sinf(phase));
                phase += inc;
                if (phase > 2.0f * (float)M_PI) phase -= 2.0f * (float)M_PI;
            }
        }
        if (!voice_play_local_pcm(buf, sizeof(buf))) return false;
    }
    return true;
}

// A sweep catches a dead driver that a single beep would pass.
static void spk_sweep(int from_hz, int to_hz, int ms, int amp)
{
    const int STEP_MS = 25;
    const int steps = ms / STEP_MS;
    for (int i = 0; i < steps; i++) {
        int f = from_hz + (to_hz - from_hz) * i / (steps > 1 ? steps - 1 : 1);
        if (!spk_tone(f, STEP_MS, amp)) return;
    }
}

void spk_play(sandy_spk_sound_t sound)
{
    // Stay well under full scale: clipping this close to the mics blinds the AEC.
    switch (sound) {
    case SPK_CHIME:
        spk_tone(880, 140, 9000); spk_tone(1175, 260, 9000);
        break;
    case SPK_ALERT:
        for (int i = 0; i < 3; i++) { spk_tone(1400, 110, 12000); spk_tone(0, 80, 0); }
        break;
    case SPK_SWEEP:
        spk_sweep(220, 3000, 900, 9000);
        break;
    case SPK_SOFT:
        spk_tone(392, 220, 4000); spk_tone(330, 320, 3500);
        break;
    case SPK_HAPPY:
        spk_tone(523, 110, 9000); spk_tone(659, 110, 9000);
        spk_tone(784, 110, 9000); spk_tone(1047, 240, 9000);
        break;
    case SPK_BEEP:
    default:
        spk_tone(880, 600, 10000);
        break;
    }
    ESP_LOGI(TAG, "played sound %d at volume %d%%", (int)sound, s_volume);
}
