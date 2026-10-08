// Dev only (ENABLE_REMOTE): the echo probe — see sandy_echo_probe.h.

#include "sandy_echo_probe.h"
#if ENABLE_REMOTE

#include <stdio.h>
#include <string.h>
#include "esp_log.h"
#include "esp_timer.h"
#include "esp_heap_caps.h"
#include "sandy_audio_ctl.h"

static const char *TAG = "echo_probe";

#define PROBE_SECONDS   10
#define PROBE_SAMPLES   (VOICE_IN_RATE * PROBE_SECONDS)
#define PROBE_ROWS      2048           // one per fetched chunk (~32 ms): ten seconds is ~320
#define SEND_PIECE      4096

typedef enum { PROBE_IDLE, PROBE_ARMED, PROBE_REC, PROBE_DONE } probe_state_t;

typedef struct {
    uint32_t at_ms;      // since the recording started
    uint32_t out_at;     // sample index in the output when this chunk was fetched
    int16_t  level, bar;
    uint8_t  talking, vad, speech, barge;
} probe_row_t;

// Allocated on the first arm and kept: a writer is never left holding a freed buffer.
static int16_t *s_feed;              // PROBE_SAMPLES × left, right, reference
static int16_t *s_out;               // PROBE_SAMPLES
static probe_row_t *s_rows;
static volatile probe_state_t s_state = PROBE_IDLE;
static volatile int s_feed_n, s_out_n, s_rows_n;
static int64_t s_t0_us, s_feed_t0_us, s_out_t0_us;
static int s_volume;

static void maybe_done(void) {
    if (s_state == PROBE_REC && s_feed_n >= PROBE_SAMPLES && s_out_n >= PROBE_SAMPLES) {
        s_state = PROBE_DONE;
        ESP_LOGW(TAG, "recording done — fetch it from the laptop");
    }
}

static void start_recording(void) {
    s_feed_n = s_out_n = s_rows_n = 0;
    s_feed_t0_us = s_out_t0_us = 0;
    s_t0_us = esp_timer_get_time();
    s_volume = spk_get_volume();
    s_state = PROBE_REC;
    ESP_LOGW(TAG, "recording %d s", PROBE_SECONDS);
}

void echo_probe_feed(const int16_t *lrr, int frames) {
    if (s_state != PROBE_REC || s_feed_n >= PROBE_SAMPLES) return;
    if (!s_feed_n) s_feed_t0_us = esp_timer_get_time();
    int n = frames;
    if (n > PROBE_SAMPLES - s_feed_n) n = PROBE_SAMPLES - s_feed_n;
    memcpy(s_feed + (size_t)s_feed_n * 3, lrr, (size_t)n * 3 * sizeof(int16_t));
    s_feed_n += n;
    maybe_done();
}

void echo_probe_out(const int16_t *pcm, int frames, bool talking, bool vad, bool speech,
                    int level, int bar, bool barge) {
    if (s_state == PROBE_ARMED && talking) start_recording();
    if (s_state != PROBE_REC || s_out_n >= PROBE_SAMPLES) return;
    if (!s_out_n) s_out_t0_us = esp_timer_get_time();
    if (s_rows_n < PROBE_ROWS) {
        s_rows[s_rows_n++] = (probe_row_t){
            .at_ms = (uint32_t)((esp_timer_get_time() - s_t0_us) / 1000),
            .out_at = (uint32_t)s_out_n,
            .level = (int16_t)(level > 32767 ? 32767 : level),
            .bar = (int16_t)(bar > 32767 ? 32767 : bar),
            .talking = talking, .vad = vad, .speech = speech, .barge = barge,
        };
    }
    int n = frames;
    if (n > PROBE_SAMPLES - s_out_n) n = PROBE_SAMPLES - s_out_n;
    memcpy(s_out + s_out_n, pcm, (size_t)n * sizeof(int16_t));
    s_out_n += n;
    maybe_done();
}

static const char *state_name(void) {
    switch (s_state) {
    case PROBE_ARMED: return "armed";
    case PROBE_REC:   return "recording";
    case PROBE_DONE:  return "done";
    default:          return "idle";
    }
}

static esp_err_t arm_get(httpd_req_t *req) {
    if (!s_feed) {
        s_feed = heap_caps_malloc((size_t)PROBE_SAMPLES * 3 * sizeof(int16_t), MALLOC_CAP_SPIRAM);
        s_out = heap_caps_malloc((size_t)PROBE_SAMPLES * sizeof(int16_t), MALLOC_CAP_SPIRAM);
        s_rows = heap_caps_malloc(PROBE_ROWS * sizeof(probe_row_t), MALLOC_CAP_SPIRAM);
        if (!s_feed || !s_out || !s_rows) {
            heap_caps_free(s_feed); heap_caps_free(s_out); heap_caps_free(s_rows);
            s_feed = NULL; s_out = NULL; s_rows = NULL;
            httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "no PSRAM for the probe");
            return ESP_FAIL;
        }
    }
    char q[16] = "";
    httpd_req_get_url_query_str(req, q, sizeof(q));
    s_state = PROBE_IDLE;
    if (strstr(q, "now")) {
        start_recording();
    } else {
        s_state = PROBE_ARMED;
        ESP_LOGW(TAG, "armed: recording starts when she starts talking");
    }
    httpd_resp_sendstr(req, state_name());
    return ESP_OK;
}

static esp_err_t status_get(httpd_req_t *req) {
    char body[320];
    snprintf(body, sizeof(body),
             "state=%s\nrate=%d\nseconds=%d\nfeed=%d\nout=%d\nrows=%d\n"
             "feed_start_ms=%lld\nout_start_ms=%lld\nvolume=%d\nref_delay_ms=%d\n"
             "mic_gain_shift=%d\nbarge_ms=%d\n",
             state_name(), VOICE_IN_RATE, PROBE_SECONDS, s_feed_n, s_out_n, s_rows_n,
             s_feed_t0_us ? (long long)((s_feed_t0_us - s_t0_us) / 1000) : -1LL,
             s_out_t0_us ? (long long)((s_out_t0_us - s_t0_us) / 1000) : -1LL,
             s_volume, VOICE_REF_DELAY_MS, VOICE_MIC_GAIN_SHIFT, VOICE_BARGE_MS);
    httpd_resp_set_type(req, "text/plain");
    httpd_resp_sendstr(req, body);
    return ESP_OK;
}

static esp_err_t send_bytes(httpd_req_t *req, const void *data, size_t len) {
    if (s_state != PROBE_DONE) {
        httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "no finished recording");
        return ESP_FAIL;
    }
    httpd_resp_set_type(req, "application/octet-stream");
    const uint8_t *p = data;
    for (size_t off = 0; off < len; off += SEND_PIECE) {
        size_t n = len - off < SEND_PIECE ? len - off : SEND_PIECE;
        if (httpd_resp_send_chunk(req, (const char *)p + off, n) != ESP_OK) return ESP_FAIL;
    }
    return httpd_resp_send_chunk(req, NULL, 0);
}

static esp_err_t feed_get(httpd_req_t *req) {
    return send_bytes(req, s_feed, (size_t)s_feed_n * 3 * sizeof(int16_t));
}

static esp_err_t out_get(httpd_req_t *req) {
    return send_bytes(req, s_out, (size_t)s_out_n * sizeof(int16_t));
}

static esp_err_t frames_get(httpd_req_t *req) {
    if (s_state != PROBE_DONE) {
        httpd_resp_send_err(req, HTTPD_404_NOT_FOUND, "no finished recording");
        return ESP_FAIL;
    }
    httpd_resp_set_type(req, "text/csv");
    httpd_resp_sendstr_chunk(req, "at_ms,out_at,talking,vad,speech,level,bar,barge\n");
    char line[80];
    for (int i = 0; i < s_rows_n; i++) {
        const probe_row_t *r = &s_rows[i];
        snprintf(line, sizeof(line), "%u,%u,%u,%u,%u,%d,%d,%u\n",
                 (unsigned)r->at_ms, (unsigned)r->out_at, r->talking, r->vad, r->speech,
                 r->level, r->bar, r->barge);
        if (httpd_resp_sendstr_chunk(req, line) != ESP_OK) return ESP_FAIL;
    }
    return httpd_resp_sendstr_chunk(req, NULL);
}

void echo_probe_register(httpd_handle_t srv) {
    const httpd_uri_t uris[] = {
        { .uri = "/echo/arm",    .method = HTTP_GET, .handler = arm_get },
        { .uri = "/echo/status", .method = HTTP_GET, .handler = status_get },
        { .uri = "/echo/feed",   .method = HTTP_GET, .handler = feed_get },
        { .uri = "/echo/out",    .method = HTTP_GET, .handler = out_get },
        { .uri = "/echo/frames", .method = HTTP_GET, .handler = frames_get },
    };
    for (size_t i = 0; i < sizeof(uris) / sizeof(uris[0]); i++) {
        httpd_register_uri_handler(srv, &uris[i]);
    }
}

#endif // ENABLE_REMOTE
