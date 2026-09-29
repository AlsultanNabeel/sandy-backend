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
#include "esp_heap_caps.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"

static const char *TAG = "ir";

// 1 µs per tick.
#define IR_RESOLUTION_HZ   1000000

// A code is µs durations alternating mark/space, starting with a mark.
#define IR_MAX_DURATIONS   400
#define IR_MAX_SYMBOLS     (IR_MAX_DURATIONS / 2)

static rmt_channel_handle_t s_tx;
static rmt_channel_handle_t s_rx;
static rmt_encoder_handle_t s_copy;

// RMT symbol halves are 15 bits: 32767 ticks = 32.7 ms.
#define IR_MAX_TICKS       32767
// Learn mode times out; while it waits, app buttons are refused.
#define IR_LEARN_TIMEOUT_MS 20000

static rmt_symbol_word_t s_rx_buf[IR_MAX_SYMBOLS];
static QueueHandle_t     s_rx_q;
static volatile bool     s_learning;
static volatile int64_t  s_learn_until_ms;

// ─── Receive ───

typedef struct {
    size_t n;
    rmt_symbol_word_t sym[IR_MAX_SYMBOLS];
} ir_frame_t;

static bool IRAM_ATTR on_rx_done(rmt_channel_handle_t ch,
                                 const rmt_rx_done_event_data_t *ev, void *arg) {
    BaseType_t woken = pdFALSE;
    // Copy out: the driver reuses its buffer.
    static ir_frame_t frame;
    frame.n = ev->num_symbols < IR_MAX_SYMBOLS ? ev->num_symbols : IR_MAX_SYMBOLS;
    memcpy(frame.sym, ev->received_symbols, frame.n * sizeof(rmt_symbol_word_t));
    xQueueSendFromISR(s_rx_q, &frame, &woken);
    return woken == pdTRUE;
}

static const rmt_receive_config_t RX_CFG = {
    // Shorter is electrical noise.
    .signal_range_min_ns = 1250,
    // Generous: air conditioners send long frames with long gaps.
    .signal_range_max_ns = 12000000,
};

// "9000,4500,560,560,…" (marks at even indices), stored and replayed as is.
static void frame_to_text(const ir_frame_t *f, char *out, size_t cap) {
    size_t k = 0;
    out[0] = '\0';
    for (size_t i = 0; i < f->n && k + 16 < cap; i++) {
        k += snprintf(out + k, cap - k, "%s%u", k ? "," : "",
                      (unsigned)f->sym[i].duration0);
        // Skip the trailing gap, or every replay gets an extra pause.
        if (i + 1 < f->n && k + 16 < cap) {
            k += snprintf(out + k, cap - k, ",%u", (unsigned)f->sym[i].duration1);
        }
    }
}

static void ir_rx_task(void *arg) {
    (void)arg;
    ir_frame_t f;
    for (;;) {
        if (xQueueReceive(s_rx_q, &f, pdMS_TO_TICKS(1000)) != pdTRUE) {
            if (s_learning && esp_timer_get_time() / 1000 > s_learn_until_ms) {
                s_learning = false;
                // Abort the pending receive, or the next "learn" finds the channel busy.
                rmt_disable(s_rx);
                rmt_enable(s_rx);
                ESP_LOGW(TAG, "learn mode timed out after %d s — nothing received",
                         IR_LEARN_TIMEOUT_MS / 1000);
            }
            continue;
        }
        if (!s_learning) continue;          // stray press outside learn mode

        if (f.n < 4) {
            ESP_LOGW(TAG, "captured %u symbols — too short to be a remote",
                     (unsigned)f.n);
            rmt_receive(s_rx, s_rx_buf, sizeof(s_rx_buf), &RX_CFG);
            continue;
        }

        // PSRAM, just for this publish.
        const size_t text_cap = IR_MAX_DURATIONS * 7;
        char *text = heap_caps_malloc(text_cap, MALLOC_CAP_SPIRAM);
        s_learning = false;
        if (!text) {
            ESP_LOGE(TAG, "no memory to report the learned code — press learn again");
            continue;
        }
        frame_to_text(&f, text, text_cap);

        ESP_LOGW(TAG, "learned %u symbols (%u chars)", (unsigned)f.n,
                 (unsigned)strlen(text));
        // Its own subtopic: a learned code is a report, not a command.
        mqtt_publish_node("ir/learned", text);   // the client copies it
        free(text);
    }
}

// ─── Transmit ───

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
        if (v > IR_MAX_TICKS) v = IR_MAX_TICKS;   // 15-bit field; a gap this long is a gap
        dur[slot++] = (unsigned)v;
        if (slot == 2) {
            // Even index = mark (carrier on).
            sym[nsym].level0    = 1;
            sym[nsym].duration0 = dur[0] ? dur[0] : 1;
            sym[nsym].level1    = 0;
            sym[nsym].duration1 = dur[1] ? dur[1] : 1;
            nsym++;
            slot = 0;
        }
    }
    // Odd count ended on a mark: add a short space (zero-length halves are rejected).
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

// ─── The one output ───

void ir_handle(const char *payload) {
    if (!payload || !*payload) return;

    if (!strcmp(payload, "learn")) {
        if (s_learning) {
            ESP_LOGI(TAG, "already learning");
            return;
        }
        s_learn_until_ms = esp_timer_get_time() / 1000 + IR_LEARN_TIMEOUT_MS;
        if (rmt_receive(s_rx, s_rx_buf, sizeof(s_rx_buf), &RX_CFG) != ESP_OK) {
            ESP_LOGE(TAG, "the receiver would not arm");
            return;
        }
        s_learning = true;
        ESP_LOGW(TAG, "learn mode — point a remote at her and press once");
        return;
    }

    // Don't learn and send at once (she'd record her own LED).
    if (s_learning) {
        ESP_LOGW(TAG, "still in learn mode — ignoring a send");
        return;
    }
    ir_send_text(payload);
}

// ─── Init ───

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

    // 38 kHz carrier: what consumer IR receivers are tuned to.
    rmt_carrier_config_t carrier = {
        .duty_cycle          = 0.33f,
        .frequency_hz        = 38000,
        .flags.polarity_active_low = false,
    };
    rmt_apply_carrier(s_tx, &carrier);

    // `= {}`, not `= { 0 }`: the struct is empty in IDF and -Werror rejects the zero.
    rmt_copy_encoder_config_t copy_cfg = {};
    e = rmt_new_copy_encoder(&copy_cfg, &s_copy);
    if (e != ESP_OK) { ESP_LOGE(TAG, "encoder: %s", esp_err_to_name(e)); return e; }
    rmt_enable(s_tx);

    rmt_rx_channel_config_t rx_cfg = {
        .gpio_num          = PIN_IR_RX,
        .clk_src           = RMT_CLK_SRC_DEFAULT,
        .resolution_hz     = IR_RESOLUTION_HZ,
        // DMA so long frames (e.g. 200-symbol AC codes) aren't cut at 128 symbols.
        .mem_block_symbols = IR_MAX_SYMBOLS,
        .flags.with_dma    = true,
    };
    e = rmt_new_rx_channel(&rx_cfg, &s_rx);
    if (e != ESP_OK) {
        // No DMA channel: fall back to channel memory.
        ESP_LOGW(TAG, "rx with DMA unavailable (%s) — long codes may be cut",
                 esp_err_to_name(e));
        rx_cfg.flags.with_dma = false;
        rx_cfg.mem_block_symbols = 128;
        e = rmt_new_rx_channel(&rx_cfg, &s_rx);
    }
    if (e != ESP_OK) { ESP_LOGE(TAG, "rx channel: %s", esp_err_to_name(e)); return e; }

    rmt_rx_event_callbacks_t cbs = { .on_recv_done = on_rx_done };
    rmt_rx_register_event_callbacks(s_rx, &cbs, NULL);
    rmt_enable(s_rx);

    // Stack in PSRAM (no flash access).
    if (xTaskCreateWithCaps(ir_rx_task, "ir_rx", 4096, NULL, 4, NULL,
                            MALLOC_CAP_SPIRAM) != pdPASS &&
        xTaskCreate(ir_rx_task, "ir_rx", 4096, NULL, 4, NULL) != pdPASS) {
        ESP_LOGE(TAG, "no memory for the receive task — learning unavailable");
    }
    ESP_LOGI(TAG, "ready — LED on GPIO %d, receiver on GPIO %d",
             PIN_IR_TX, PIN_IR_RX);
    return ESP_OK;
}

#endif  // ENABLE_IR
