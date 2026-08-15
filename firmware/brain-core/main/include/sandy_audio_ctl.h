#pragma once
#include <stdbool.h>
#include <stdint.h>

// Runtime control over the two microphones and the speaker.
//
// Neither part is adjustable in hardware. The INMP441 is a fixed-gain digital
// MEMS mic — its sensitivity is set by the part, not by a register — and the
// MAX98357A's gain is strapped by a pin. So everything here is applied in the
// digital domain, on the samples, between the I2S read and the mix (mics) or
// between the buffer and the I2S write (speaker).
//
// That distinction matters when reading the values: "gain 150" is not the mic
// becoming more sensitive, it is the captured signal multiplied by 1.5. Turning
// it up amplifies the room noise floor along with the voice, so past roughly 200
// you are making the wake word worse, not better. The clamp is deliberate.
//
// Every setting survives a reboot (NVS) — a robot that forgets you muted a dead
// mic is a robot you have to fix twice.

#define AUDIO_GAIN_MIN      0     // silent
#define AUDIO_GAIN_UNITY  100     // untouched
#define AUDIO_GAIN_MAX    300     // 3x, past which the noise floor dominates

typedef enum {
    MIC_LEFT = 0,
    MIC_RIGHT,
    MIC_COUNT
} sandy_mic_ch_t;

void audio_ctl_init(void);   // loads saved values; safe before I2S is up

// ── Microphones ──────────────────────────────────────────────────────────────

// Digital gain per channel, in percent (100 = unchanged). Clamped to
// [AUDIO_GAIN_MIN, AUDIO_GAIN_MAX]. Persisted.
void     mic_set_gain(sandy_mic_ch_t ch, int percent);
int      mic_get_gain(sandy_mic_ch_t ch);

// Mute one microphone. A muted channel contributes nothing to the mix, which is
// how you test the other one on its own. Muting BOTH would leave her deaf, so
// the second mute is refused and returns false — a robot should not be able to
// take its own hearing away because a slider went to zero.
bool     mic_set_muted(sandy_mic_ch_t ch, bool muted);
bool     mic_is_muted(sandy_mic_ch_t ch);

// Apply gain + mute to one stereo frame. Called per sample from the mic task,
// so it is a header-inlined multiply — no branching on state that a task could
// change mid-frame.
static inline int32_t mic_apply(int32_t sample, int gain_pct, bool muted) {
    if (muted) return 0;
    if (gain_pct == AUDIO_GAIN_UNITY) return sample;
    return (sample * gain_pct) / 100;
}

// Live input level per channel, 0..100, smoothed. This is what a control screen
// draws as a meter: speak, and watch which mic moves. Updated by the mic task.
int      mic_get_level(sandy_mic_ch_t ch);
void     mic_report_levels(int rms_l, int rms_r);   // mic task -> here

// ── Noise suppression ────────────────────────────────────────────────────────
//
// Steady background noise — a fan, an air conditioner, a fridge — is what stops
// the wake word working from across a room. The WebRTC suppressor that removes
// it is already compiled into this firmware (`CONFIG_SR_NSN_WEBRTC=y` in
// sdkconfig); nothing was ever calling it, so the fan went straight through to
// the cloud.
//
// It is a slider and not a switch on purpose: suppression works by deciding what
// is noise and subtracting it, and the aggressive setting takes pieces of quiet
// speech with it. Mild is right in a normal room; aggressive is for a fan running
// next to her.
//
// This is NOT the same thing as echo cancellation (that removes *her own* voice
// so she can be interrupted, and runs separately), and it is not beamforming
// (using both mics to favour the direction you are speaking from — better still,
// and a larger change to the pipeline than this one).

typedef enum {
    NS_OFF = 0,
    NS_MILD,        // normal room
    NS_MEDIUM,
    NS_AGGRESSIVE,  // a fan running right next to her
    NS_LEVEL_COUNT
} sandy_ns_level_t;

// The suppressor works on fixed 10 ms blocks at 16 kHz — 160 samples.
#define NS_FRAME_SAMPLES 160

void             ns_set_level(sandy_ns_level_t level);   // persisted
sandy_ns_level_t ns_get_level(void);

// Clean one buffer in place. Length must be a multiple of NS_FRAME_SAMPLES; any
// remainder is left untouched rather than misaligned. A no-op when the level is
// off or the instance could not be created, so callers never branch on it.
void             ns_clean(int16_t *pcm, int samples);

// ── Speaker ──────────────────────────────────────────────────────────────────

// Output volume 0..100. Persisted. 100 is the unmodified stream — this only ever
// attenuates, because amplifying a full-scale sample just clips it.
void     spk_set_volume(int percent);
int      spk_get_volume(void);

// Scale one output sample by the current volume.
int16_t  spk_apply(int16_t sample);

// ── Speaker sounds ───────────────────────────────────────────────────────────
//
// Generated on the board, played through the same buffer her cloud voice uses.
// That routing is the point: a sound that arrives means the whole output path
// works — buffer, volume, amp, speaker — not that a second channel could be
// opened alongside a broken one.
//
// These are the speaker's answer to the buzzer's melodies. The buzzer is a piezo
// on one pin and sounds like a toy; this is the real amplifier, so it can do
// chords, sweeps and something soft enough to use at night.
typedef enum {
    SPK_BEEP = 0,   // the plain confidence check
    SPK_CHIME,      // two-note, gentle — an "I heard you"
    SPK_ALERT,      // three sharp pulses, meant to interrupt
    SPK_SWEEP,      // rising sweep — proves the whole frequency range, not one tone
    SPK_SOFT,       // low and quiet, for night
    SPK_HAPPY,      // a small rising arpeggio
    SPK_SOUND_COUNT
} sandy_spk_sound_t;

// Play one. Blocks for its duration on the caller's task, so call it from a
// command handler and not from anything real-time.
void     spk_play(sandy_spk_sound_t sound);

// Kept for the existing call sites: the plain beep.
void     spk_test_tone(void);
