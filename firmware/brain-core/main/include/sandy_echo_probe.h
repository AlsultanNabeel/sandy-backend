#pragma once
// Dev only (ENABLE_REMOTE): records ten seconds of what the audio front end is fed
// (both mics and the speaker reference, interleaved exactly as it sees them) and what it
// gives back (the voice after echo cancelling), starting the moment she starts talking.
// Fetched over the dev web server; scripts/echo_probe.py arms it, downloads and analyses.
#include <stdbool.h>
#include <stdint.h>
#include "config.h"

#if ENABLE_REMOTE
#include "esp_http_server.h"

// The dev web server's handlers: /echo/arm, /echo/status, /echo/feed, /echo/out, /echo/frames.
void echo_probe_register(httpd_handle_t srv);
// mic_task: one front-end feed chunk, `frames` samples of left, right, reference.
void echo_probe_feed(const int16_t *lrr, int frames);
// proc_task: one fetched chunk (before the output gain) and what was decided on it.
void echo_probe_out(const int16_t *pcm, int frames, bool talking, bool vad, bool speech,
                    int level, int bar, bool barge);
#else
static inline void echo_probe_feed(const int16_t *lrr, int frames) { (void)lrr; (void)frames; }
static inline void echo_probe_out(const int16_t *pcm, int frames, bool talking, bool vad,
                                  bool speech, int level, int bar, bool barge) {
    (void)pcm; (void)frames; (void)talking; (void)vad; (void)speech;
    (void)level; (void)bar; (void)barge;
}
#endif
