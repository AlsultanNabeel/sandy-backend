#include "config.h"
#if ENABLE_IR

#include "sandy_ir.h"
#include "sandy_mqtt.h"

#include <string.h>
#include <stdio.h>
#include <stdlib.h>

#include "driver/rmt_tx.h"
#include "driver/rmt_rx.h"
#include "driver/rmt_encoder.h"
#include "esp_log.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

static const char *TAG = "ir";

// One microsecond per tick. IR timings are tens to thousands of microseconds, so
// this is the natural unit and the recorded code reads as the real thing.
#define IR_RESOLUTION_HZ   1000000

// A recorded code is a list of durations in microseconds, alternating mark and
// space, **starting with a mark**. That ordering is the whole format: without it
// a replay inverts every pulse and the appliance sees silence.
#define IR_MAX_DURATIONS   400
#define IR_MAX_SYMBOLS     (IR_MAX_DURATIONS / 2)

static rmt_channel_handle_t s_tx;
static rmt_channel_handle_t s_rx;
static rmt_encoder_handle_t s_copy;

static rmt_symbol_word_t s_rx_buf[IR_MAX_SYMBOLS];
static QueueHandle_t     s_rx_q;
static volatile bool     s_learning;

// ─── Receive ─────────────────────────────────────────────────────────────────

typedef struct {
    size_t n;
    rmt_symbol_word_t sym[IR_MAX_SYMBOLS];
} ir_frame_t;

static bool IRAM_ATTR on_rx_done(rmt_channel_handle_t ch,
                                 const rmt_rx_done_event_data_t *ev, void *arg) {
    BaseType_t woken = pdFALSE;
    // Copied out here rather than passed by pointer: the driver reuses its
    // buffer for the next frame the moment this returns.
    static ir_frame_t frame;
    frame.n = ev->num_symbols < IR_MAX_SYMBOLS ? ev->num_symbols : IR_MAX_SYMBOLS;
    memcpy(frame.sym, ev->received_symbols, frame.n * sizeof(rmt_symbol_word_t));
    xQueueSendFromISR(s_rx_q, &frame, &woken);
    return woken == pdTRUE;
}

static const rmt_receive_config_t RX_CFG = {
    // Below this is electrical noise, not a pulse from a remote.
    .signal_range_min_ns = 1250,
    // Silence longer than this ends the frame. Generous on purpose: air
    // conditioners send long frames with long gaps, and cutting one in half
    // yields a code that stores, replays, and does nothing.
    .signal_range_max_ns = 12000000,
};

// The captured frame as text: "9000,4500,560,560,…" — marks at the even
// indices. Stored in the device's button map exactly like this and handed back
// on replay, so what the appliance receives is what it sent.
static void frame_to_text(const ir_frame_t *f, char *out, size_t cap) {
    size_t k = 0;
    out[0] = '\0';
    for (size_t i = 0; i < f->n && k + 16 < cap; i++) {
        k += snprintf(out + k, cap - k, "%s%u", k ? "," : "",
                      (unsigned)f->sym[i].duration0);
        // The last symbol's trailing space is the gap before the next frame, not
        // part of this one. Recording it would add a pause to every replay.
        if (i + 1 < f->n && k + 16 < cap) {
            k += snprintf(out + k, cap - k, ",%u", (unsigned)f->sym[i].duration1);
        }
    }
}

static void ir_rx_task(void *arg) {
    (void)arg;
    ir_frame_t f;
    for (;;) {
        if (xQueueReceive(s_rx_q, &f, portMAX_DELAY) != pdTRUE) continue;
        if (!s_learning) continue;          // stray press outside learn mode

        if (f.n < 4) {
            ESP_LOGW(TAG, "captured %u symbols — too short to be a remote",
                     (unsigned)f.n);
            rmt_receive(s_rx, s_rx_buf, sizeof(s_rx_buf), &RX_CFG);
            continue;
        }

        static char text[IR_MAX_DURATIONS * 7];
        frame_to_text(&f, text, sizeof(text));
        s_learning = false;

        ESP_LOGW(TAG, "learned %u symbols (%u chars)", (unsigned)f.n,
                 (unsigned)strlen(text));
        // The backend stores this against the node and the app binds it to a
        // button. Publishing on its own subtopic keeps it out of the command
        // path — a learned code is a report, not an instruction.
        mqtt_publish_node("ir/learned", text);
    }
}

// ─── Transmit ────────────────────────────────────────────────────────────────

static void ir_send_text(const char *code) {
    static rmt_symbol_word_t sym[IR_MAX_SYMBOLS];
    size_t nsym = 0;
    unsigned dur[2] = {0, 0};
    int slot = 0;

    const char *p = code;
    while (*p && nsym < IR_MAX_SYMBOLS) {
        while (*p == ' ' || *p == ',') p++;
        if (!*p) break;
        char *end = NULL;
        unsigned long v = strtoul(p, &end, 10);
        if (end == p) break;                 // not a number: stop, don't guess
        p = end;
        dur[slot++] = (unsigned)v;
        if (slot == 2) {
            // Even index is the mark — carrier on. This is the one line that
            // depends on the format's ordering, and inverting it produces a
            // replay that looks perfect on a scope and does nothing in the room.
            sym[nsym].level0    = 1;
            sym[nsym].duration0 = dur[0] ? dur[0] : 1;
            sym[nsym].level1    = 0;
            sym[nsym].duration1 = dur[1] ? dur[1] : 1;
            nsym++;
            slot = 0;
        }
    }
    // An odd count means the code ended on a mark. Give it a short space to
    // close on; a symbol with a zero-length second half is rejected by the
    // driver and the whole frame would be dropped.
    if (slot == 1 && nsym < IR_MAX_SYMBOLS) {
        sym[nsym].level0    = 1;
        sym[nsym].duration0 = dur[0] ? dur[0] : 1;
        sym[nsym].level1    = 0;
        sym[nsym].duration1 = 1000;
        nsym++;
    }

    if (nsym == 0) {
        ESP_LOGW(TAG, "nothing to send — the code held no timings");
        return;
    }

    rmt_transmit_config_t tx = { .loop_count = 0 };
    esp_err_t e = rmt_transmit(s_tx, s_copy, sym,
                               nsym * sizeof(rmt_symbol_word_t), &tx);
    if (e != ESP_OK) {
        ESP_LOGE(TAG, "transmit failed: %s", esp_err_to_name(e));
        return;
    }
    rmt_tx_wait_all_done(s_tx, 1000);
    ESP_LOGI(TAG, "sent %u symbols", (unsigned)nsym);
}

// ─── The one output ──────────────────────────────────────────────────────────

void ir_handle(const char *payload) {
    if (!payload || !*payload) return;

    if (!strcmp(payload, "learn")) {
        s_learning = true;
        rmt_receive(s_rx, s_rx_buf, sizeof(s_rx_buf), &RX_CFG);
        ESP_LOGW(TAG, "learn mode — point a remote at her and press once");
        return;
    }

    // Learning and sending at the same moment would have her record her own
    // LED. Cheap to prevent, confusing to debug.
    if (s_learning) {
        ESP_LOGW(TAG, "still in learn mode — ignoring a send");
        return;
    }
    ir_send_text(payload);
}

// ─── Init ────────────────────────────────────────────────────────────────────

esp_err_t ir_init(void) {
    s_rx_q = xQueueCreate(2, sizeof(ir_frame_t));
    if (!s_rx_q) return ESP_ERR_NO_MEM;

    rmt_tx_channel_config_t tx_cfg = {
        .gpio_num          = PIN_IR_TX,
        .clk_src           = RMT_CLK_SRC_DEFAULT,
        .resolution_hz     = IR_RESOLUTION_HZ,
        .mem_block_symbols = 64,
        .trans_queue_depth = 4,
    };
    esp_err_t e = rmt_new_tx_channel(&tx_cfg, &s_tx);
    if (e != ESP_OK) { ESP_LOGE(TAG, "tx channel: %s", esp_err_to_name(e)); return e; }

    // 38 kHz is what the receivers in consumer gear are tuned to, and the
    // carrier is what makes a pulse train visible to them at all — without it
    // the LED flashes and nothing in the room reacts.
    rmt_carrier_config_t carrier = {
        .duty_cycle          = 0.33f,
        .frequency_hz        = 38000,
        .flags.polarity_active_low = false,
    };
    rmt_apply_carrier(s_tx, &carrier);

    // `= {}` and not `= { 0 }`: this config struct is **empty** in IDF, so a
    // zero initialiser is one element too many and -Werror stops the build.
    // Matches what IDF's own RMT examples do.
    rmt_copy_encoder_config_t copy_cfg = {};
    e = rmt_new_copy_encoder(&copy_cfg, &s_copy);
    if (e != ESP_OK) { ESP_LOGE(TAG, "encoder: %s", esp_err_to_name(e)); return e; }
    rmt_enable(s_tx);

    rmt_rx_channel_config_t rx_cfg = {
        .gpio_num          = PIN_IR_RX,
        .clk_src           = RMT_CLK_SRC_DEFAULT,
        .resolution_hz     = IR_RESOLUTION_HZ,
        .mem_block_symbols = 128,
    };
    e = rmt_new_rx_channel(&rx_cfg, &s_rx);
    if (e != ESP_OK) { ESP_LOGE(TAG, "rx channel: %s", esp_err_to_name(e)); return e; }

    rmt_rx_event_callbacks_t cbs = { .on_recv_done = on_rx_done };
    rmt_rx_register_event_callbacks(s_rx, &cbs, NULL);
    rmt_enable(s_rx);

    xTaskCreate(ir_rx_task, "ir_rx", 4096, NULL, 4, NULL);
    ESP_LOGI(TAG, "ready — LED on GPIO %d, receiver on GPIO %d",
             PIN_IR_TX, PIN_IR_RX);
    return ESP_OK;
}

#endif  // ENABLE_IR
