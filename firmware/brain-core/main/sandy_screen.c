// Showing the owner's text or picture on Sandy's display.
// Contract and reasoning: include/sandy_screen.h
//
// Threading, which is the only subtle part:
//
// LVGL is not thread-safe and every object here belongs to the LVGL task. So
// nothing in this file touches an LVGL object from a caller's thread. MQTT (or
// anything else) writes plain state under a mutex and sets a dirty flag;
// `screen_lvgl_tick()`, which sandy_face runs from an LVGL timer, is the only
// code that draws. Same shape as the status banner next door — one rule for the
// whole display instead of two.

#include "config.h"
#if ENABLE_FACE

#include "sandy_screen.h"
#include <string.h>
#include "esp_log.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "lvgl.h"

static const char *TAG = "screen";

#define IMG_BYTES   (SCREEN_W * SCREEN_H * 2)   // RGB565
#define MAX_CHUNKS  64
#define TEXT_MAX    256

// ── State written by callers, read by the LVGL task ──────────────────────────
static SemaphoreHandle_t s_lock;

static char     s_text[TEXT_MAX];
static bool     s_want_text;
static bool     s_want_image;
static bool     s_want_dismiss;
static bool     s_dirty;
static bool     s_showing;

// The image buffer, PSRAM. Allocated on the first transfer and kept: taking and
// returning 115 KB per picture would fragment PSRAM for no gain, and this board
// has eight megabytes of it.
static uint8_t *s_img;
static int      s_expect_chunks;
static uint32_t s_have_mask[(MAX_CHUNKS + 31) / 32];
static int      s_have_count;

// ── LVGL objects, touched only on the LVGL task ──────────────────────────────
static lv_obj_t     *s_panel;
static lv_obj_t     *s_label;
static lv_obj_t     *s_img_obj;
static lv_img_dsc_t  s_img_dsc;

// ── Helpers ──────────────────────────────────────────────────────────────────

static bool lock(void) {
    return s_lock && xSemaphoreTake(s_lock, pdMS_TO_TICKS(50)) == pdTRUE;
}

static void unlock(void) {
    if (s_lock) xSemaphoreGive(s_lock);
}

static bool chunk_seen(int seq) {
    return (s_have_mask[seq / 32] >> (seq % 32)) & 1u;
}

static void chunk_mark(int seq) {
    s_have_mask[seq / 32] |= 1u << (seq % 32);
}

// ── Called by sandy_face, on the LVGL task ───────────────────────────────────

void screen_lvgl_build(lv_obj_t *parent) {
    s_lock = xSemaphoreCreateMutex();

    s_panel = lv_obj_create(parent);
    lv_obj_set_size(s_panel, TFT_WIDTH, TFT_HEIGHT);
    lv_obj_set_pos(s_panel, 0, 0);
    lv_obj_set_style_bg_color(s_panel, lv_color_black(), 0);
    lv_obj_set_style_bg_opa(s_panel, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(s_panel, 0, 0);
    lv_obj_set_style_pad_all(s_panel, 0, 0);
    lv_obj_set_style_radius(s_panel, 0, 0);
    lv_obj_clear_flag(s_panel, LV_OBJ_FLAG_SCROLLABLE);
    lv_obj_add_flag(s_panel, LV_OBJ_FLAG_HIDDEN);

    s_img_obj = lv_img_create(s_panel);
    lv_obj_center(s_img_obj);
    lv_obj_add_flag(s_img_obj, LV_OBJ_FLAG_HIDDEN);

    s_label = lv_label_create(s_panel);
    lv_obj_set_width(s_label, TFT_WIDTH - 24);
    lv_label_set_long_mode(s_label, LV_LABEL_LONG_WRAP);
    lv_obj_set_style_text_align(s_label, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_set_style_text_color(s_label, lv_color_white(), 0);
#if LV_FONT_DEJAVU_16_PERSIAN_HEBREW
    // Arabic needs a font that has the glyphs; Montserrat does not. With
    // LV_USE_BIDI and LV_USE_ARABIC_PERSIAN_CHARS on, LVGL also joins the
    // letters and lays the line out right-to-left, which is what separates
    // readable Arabic from a row of disconnected shapes.
    lv_obj_set_style_text_font(s_label, &lv_font_dejavu_16_persian_hebrew, 0);
#endif
    lv_obj_center(s_label);
    lv_obj_add_flag(s_label, LV_OBJ_FLAG_HIDDEN);

    ESP_LOGI(TAG, "ready");
}

void screen_lvgl_tick(void) {
    if (!s_dirty || !s_panel) return;
    if (!lock()) return;

    bool want_text    = s_want_text;
    bool want_image   = s_want_image;
    bool want_dismiss = s_want_dismiss;
    s_want_text = s_want_image = s_want_dismiss = false;
    s_dirty = false;

    if (want_dismiss) {
        lv_obj_add_flag(s_panel, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_img_obj, LV_OBJ_FLAG_HIDDEN);
        s_showing = false;
        unlock();
        ESP_LOGI(TAG, "dismissed — face is back");
        return;
    }

    if (want_text) {
        lv_label_set_text(s_label, s_text);
        lv_obj_center(s_label);
        lv_obj_clear_flag(s_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_img_obj, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(s_panel, LV_OBJ_FLAG_HIDDEN);
        s_showing = true;
    }

    if (want_image && s_img) {
        s_img_dsc.header.always_zero = 0;
        s_img_dsc.header.w  = SCREEN_W;
        s_img_dsc.header.h  = SCREEN_H;
        s_img_dsc.header.cf = LV_IMG_CF_TRUE_COLOR;
        s_img_dsc.data_size = IMG_BYTES;
        s_img_dsc.data      = s_img;
        lv_img_set_src(s_img_obj, &s_img_dsc);
        lv_obj_center(s_img_obj);
        lv_obj_clear_flag(s_img_obj, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(s_panel, LV_OBJ_FLAG_HIDDEN);
        // The cached copy is the old picture; without this the panel keeps
        // showing what it drew last time even though the bytes changed.
        lv_img_cache_invalidate_src(&s_img_dsc);
        lv_obj_invalidate(s_img_obj);
        s_showing = true;
    }

    unlock();
}

// ── Called from anywhere ─────────────────────────────────────────────────────

void screen_show_text(const char *text) {
    if (!text || !*text) { screen_dismiss(); return; }
    if (!lock()) return;
    strncpy(s_text, text, sizeof(s_text) - 1);
    s_text[sizeof(s_text) - 1] = '\0';
    s_want_text  = true;
    s_want_image = false;
    s_dirty      = true;
    unlock();
    ESP_LOGI(TAG, "text queued (%d chars)", (int)strlen(s_text));
}

void screen_dismiss(void) {
    if (!lock()) return;
    s_want_dismiss = true;
    s_want_text = s_want_image = false;
    s_dirty = true;
    unlock();
}

bool screen_is_showing(void) {
    return s_showing;
}

bool screen_image_begin(int total_chunks) {
    if (total_chunks < 1 || total_chunks > MAX_CHUNKS) {
        ESP_LOGW(TAG, "refused: %d chunks is outside 1..%d", total_chunks, MAX_CHUNKS);
        return false;
    }
    if (!lock()) return false;

    if (!s_img) {
        // PSRAM, never internal. Internal RAM is what the voice session needs,
        // and a picture must not be the reason she cannot talk.
        s_img = heap_caps_malloc(IMG_BYTES, MALLOC_CAP_SPIRAM);
        if (!s_img) {
            unlock();
            ESP_LOGE(TAG, "no PSRAM for a %d-byte image", IMG_BYTES);
            return false;
        }
    }
    memset(s_have_mask, 0, sizeof(s_have_mask));
    s_have_count    = 0;
    s_expect_chunks = total_chunks;
    unlock();
    ESP_LOGI(TAG, "image incoming, %d chunks", total_chunks);
    return true;
}

void screen_image_chunk(int seq, const uint8_t *data, size_t len) {
    if (!data || len == 0) return;
    if (!lock()) return;

    // Every one of these is a refusal, not a clamp. The payload arrives over a
    // shared broker from something nobody authenticated, so a piece that does
    // not fit where it claims to go is dropped rather than trimmed to fit.
    if (!s_img || s_expect_chunks <= 0) { unlock(); return; }
    if (seq < 0 || seq >= s_expect_chunks) { unlock(); return; }
    if (chunk_seen(seq)) { unlock(); return; }

    size_t chunk_size = (IMG_BYTES + s_expect_chunks - 1) / s_expect_chunks;
    size_t offset     = (size_t)seq * chunk_size;
    if (offset >= IMG_BYTES) { unlock(); return; }
    size_t room = IMG_BYTES - offset;
    if (len > room) len = room;

    memcpy(s_img + offset, data, len);
    chunk_mark(seq);
    s_have_count++;
    unlock();
}

bool screen_image_end(void) {
    if (!lock()) return false;
    bool complete = (s_expect_chunks > 0 && s_have_count >= s_expect_chunks);
    if (complete) {
        s_want_image   = true;
        s_want_text    = false;
        s_want_dismiss = false;
        s_dirty        = true;
    }
    int have = s_have_count, want = s_expect_chunks;
    s_expect_chunks = 0;
    unlock();

    if (!complete) {
        // Naming the shortfall matters: "it did not appear" and "eleven of
        // twelve pieces arrived" send you to completely different places.
        ESP_LOGW(TAG, "image incomplete — %d of %d chunks; nothing drawn", have, want);
        return false;
    }
    ESP_LOGI(TAG, "image complete (%d chunks)", have);
    return true;
}

#endif // ENABLE_FACE
