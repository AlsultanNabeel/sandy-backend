#pragma once
#include <stdbool.h>
#include <stdint.h>

// Runtime mic/speaker control, applied digitally on samples (neither INMP441 nor
// MAX98357A is adjustable). Gain amplifies room noise too, hence the clamp.
// All settings persist in NVS.

#define AUDIO_GAIN_MIN      0     // silent
#define AUDIO_GAIN_UNITY  100     // untouched
#define AUDIO_GAIN_MAX    300     // 3x, past which the noise floor dominates

typedef enum {
    MIC_LEFT = 0,
    MIC_RIGHT,
    MIC_COUNT
} sandy_mic_ch_t;

void audio_ctl_init(void);   // loads saved values; safe before I2S is up

// ── Microphones ──

// Percent (100 = unchanged), clamped, persisted.
void     mic_set_gain(sandy_mic_ch_t ch, int percent);
int      mic_get_gain(sandy_mic_ch_t ch);

// Muting both would leave her deaf, so the second mute is refused (false).
bool     mic_set_muted(sandy_mic_ch_t ch, bool muted);
bool     mic_is_muted(sandy_mic_ch_t ch);

// Per sample in the mic task, so kept inline and branch-light.
static inline int32_t mic_apply(int32_t sample, int gain_pct, bool muted) {
    if (muted) return 0;
    if (gain_pct == AUDIO_GAIN_UNITY) return sample;
    return (sample * gain_pct) / 100;
}

// Smoothed 0..100 input level for the app's meter.
int      mic_get_level(sandy_mic_ch_t ch);
void     mic_report_levels(int rms_l, int rms_r);   // mic task -> here

// Noise suppression (WebRTC NS, already in sdkconfig). A level, not a switch:
// aggressive settings also eat quiet speech. Separate from echo cancellation.

typedef enum {
    NS_OFF = 0,
    NS_MILD,        // normal room
    NS_MEDIUM,
    NS_AGGRESSIVE,  // a fan running right next to her
    NS_LEVEL_COUNT
} sandy_ns_level_t;

// 10 ms at 16 kHz.
#define NS_FRAME_SAMPLES 160

void             ns_set_level(sandy_ns_level_t level);   // persisted
sandy_ns_level_t ns_get_level(void);

// In place; length must be a multiple of NS_FRAME_SAMPLES (remainder untouched).
// No-op when off or unavailable.
void             ns_clean(int16_t *pcm, int samples);

// ── Speaker ──

// 0..100, persisted. Only attenuates: amplifying full-scale samples clips.
void     spk_set_volume(int percent);
int      spk_get_volume(void);

int16_t  spk_apply(int16_t sample);

// Board-generated sounds played through the voice buffer, so a sound proves the
// real output path.
typedef enum {
    SPK_BEEP = 0,   // the plain confidence check
    SPK_CHIME,      // two-note, gentle — an "I heard you"
    SPK_ALERT,      // three sharp pulses, meant to interrupt
    SPK_SWEEP,      // rising sweep across the frequency range
    SPK_SOFT,       // low and quiet, for night
    SPK_HAPPY,      // a small rising arpeggio
    SPK_SOUND_COUNT
} sandy_spk_sound_t;

// Queues and returns at once (tones that don't fit are dropped); safe from MQTT.
void     spk_play(sandy_spk_sound_t sound);
