// Owner's text or picture on the display (see sandy_screen.h).
// LVGL isn't thread-safe: callers set state under a mutex, and only
// screen_lvgl_tick() (on the LVGL task) draws.

#include "config.h"
#if ENABLE_FACE

#include "sandy_screen.h"
#include <stdio.h>
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

// ── State written by callers, read by the LVGL task ──
static SemaphoreHandle_t s_lock;

static char     s_text[TEXT_MAX];
static bool     s_want_text;
static bool     s_want_image;
static bool     s_want_dismiss;
static bool     s_want_qr;
static char     s_qr_payload[128];
static lv_obj_t *s_qr;          // built on first use
static lv_obj_t *s_qr_caption;
static bool     s_dirty;
static bool     s_showing;

// ── Text size ──
// LVGL's only Arabic font is 16 px; the other sizes are generated (main/fonts).
LV_FONT_DECLARE(sandy_font_ar_24);
LV_FONT_DECLARE(sandy_font_ar_32);

static sandy_screen_size_t s_size = SCREEN_SIZE_MEDIUM;

static const lv_font_t *font_for(sandy_screen_size_t size) {
    switch (size) {
    case SCREEN_SIZE_LARGE:  return &sandy_font_ar_32;
    case SCREEN_SIZE_MEDIUM: return &sandy_font_ar_24;
    case SCREEN_SIZE_SMALL:
    default:
#if LV_FONT_DEJAVU_16_PERSIAN_HEBREW
        // With LV_USE_BIDI and LV_USE_ARABIC_PERSIAN_CHARS, LVGL joins letters RTL.
        return &lv_font_dejavu_16_persian_hebrew;
#else
        return &sandy_font_ar_24;
#endif
    }
}

// PSRAM, allocated on first transfer and kept (avoids fragmentation).
static uint8_t *s_img;        // what LVGL draws
// Received separately and swapped in whole, so a failed transfer never corrupts the shown one.
static uint8_t *s_img_rx;
static size_t   s_rx_bytes;   // bytes of it actually received
static int      s_expect_chunks;
// من القطعة الأولى، مش بالقسمة.
static size_t   s_chunk_size;
static uint32_t s_have_mask[(MAX_CHUNKS + 31) / 32];
static int      s_have_count;

// ── LVGL objects, touched only on the LVGL task ──
static lv_obj_t     *s_panel;
static lv_obj_t     *s_label;
static lv_obj_t     *s_img_obj;
static lv_img_dsc_t  s_img_dsc;

// ── Helpers ──

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

// ── Called by sandy_face, on the LVGL task ──

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
    lv_obj_set_style_text_font(s_label, font_for(s_size), 0);
    lv_obj_center(s_label);
    lv_obj_add_flag(s_label, LV_OBJ_FLAG_HIDDEN);

    ESP_LOGI(TAG, "ready");
}

void screen_set_size(sandy_screen_size_t size) {
    if (size < SCREEN_SIZE_SMALL || size > SCREEN_SIZE_LARGE) return;
    if (!lock()) return;
    s_size = size;
    // Redraw only if a line is up; don't hide the face to show a size change.
    if (s_showing) { s_want_text = true; s_dirty = true; }
    unlock();
    ESP_LOGI(TAG, "text size = %d", (int)size);
}

sandy_screen_size_t screen_size_from_name(const char *name) {
    if (!name) return SCREEN_SIZE_MEDIUM;
    if (!strcmp(name, "small"))  return SCREEN_SIZE_SMALL;
    if (!strcmp(name, "large"))  return SCREEN_SIZE_LARGE;
    return SCREEN_SIZE_MEDIUM;
}

void screen_lvgl_tick(void) {
    if (!s_dirty || !s_panel) return;
    if (!lock()) return;

    bool want_text    = s_want_text;
    bool want_image   = s_want_image;
    bool want_dismiss = s_want_dismiss;
    bool want_qr      = s_want_qr;
    s_want_text = s_want_image = s_want_dismiss = s_want_qr = false;
    s_dirty = false;

    // A QR stays only while it is what's shown.
    if ((want_dismiss || want_text || want_image) && s_qr) {
        lv_obj_add_flag(s_qr, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_qr_caption, LV_OBJ_FLAG_HIDDEN);
    }
#if LV_USE_QRCODE
    if (want_qr) {
        if (!s_qr) {
            s_qr = lv_qrcode_create(s_panel, 170, lv_color_black(), lv_color_white());
            // White quiet zone, or phones won't read it.
            lv_obj_set_style_border_color(s_qr, lv_color_white(), 0);
            lv_obj_set_style_border_width(s_qr, 8, 0);
            lv_obj_align(s_qr, LV_ALIGN_TOP_MID, 0, 14);
            s_qr_caption = lv_label_create(s_panel);
            lv_obj_set_width(s_qr_caption, TFT_WIDTH - 16);
            lv_obj_set_style_text_align(s_qr_caption, LV_TEXT_ALIGN_CENTER, 0);
            lv_obj_set_style_text_color(s_qr_caption, lv_color_white(), 0);
            lv_obj_align(s_qr_caption, LV_ALIGN_BOTTOM_MID, 0, -10);
        }
        lv_qrcode_update(s_qr, s_qr_payload, strlen(s_qr_payload));
        lv_label_set_text(s_qr_caption, s_text);
        lv_obj_clear_flag(s_qr, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(s_qr_caption, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_label, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_img_obj, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(s_panel, LV_OBJ_FLAG_HIDDEN);
        s_showing = true;
    }
#else
    if (want_qr) want_text = true;   // no QR widget: caption only
#endif

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
        lv_obj_set_style_text_font(s_label, font_for(s_size), 0);
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
        // Invalidate the cache or the old picture stays.
        lv_img_cache_invalidate_src(&s_img_dsc);
        lv_obj_invalidate(s_img_obj);
        s_showing = true;
    }

    unlock();
}

// ── Called from anywhere ──

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

void screen_show_qr(const char *payload, const char *caption) {
    if (!payload || !*payload) return;
    if (!lock()) return;
    snprintf(s_qr_payload, sizeof(s_qr_payload), "%s", payload);
    snprintf(s_text, sizeof(s_text), "%s", caption ? caption : "");
    s_want_qr    = true;
    s_want_text  = false;
    s_want_image = false;
    s_dirty      = true;
    unlock();
}

void screen_dismiss(void) {
    if (!lock()) return;
    s_want_dismiss = true;
    s_want_text = s_want_image = false;
    s_dirty = true;
    unlock();
}

bool screen_image_begin(int total_chunks) {
    if (total_chunks < 1 || total_chunks > MAX_CHUNKS) {
        ESP_LOGW(TAG, "refused: %d chunks is outside 1..%d", total_chunks, MAX_CHUNKS);
        return false;
    }
    if (!lock()) return false;

    if (!s_img_rx) {
        // PSRAM, never internal (voice needs it).
        s_img_rx = heap_caps_malloc(IMG_BYTES, MALLOC_CAP_SPIRAM);
        if (!s_img_rx) {
            unlock();
            ESP_LOGE(TAG, "no PSRAM for a %d-byte image", IMG_BYTES);
            return false;
        }
    }
    memset(s_have_mask, 0, sizeof(s_have_mask));
    s_rx_bytes      = 0;
    s_have_count    = 0;
    s_chunk_size    = 0;      // تتحدّد من القطعة الأولى
    s_expect_chunks = total_chunks;
    unlock();
    ESP_LOGI(TAG, "image incoming, %d chunks", total_chunks);
    return true;
}

void screen_image_chunk(int seq, const uint8_t *data, size_t len) {
    if (!data || len == 0) return;
    if (!lock()) return;

    // Untrusted broker input: refuse misfitting pieces, never trim.
    if (!s_img_rx || s_expect_chunks <= 0) { unlock(); return; }
    if (seq < 0 || seq >= s_expect_chunks) { unlock(); return; }
    if (chunk_seen(seq)) { unlock(); return; }

    // مقاس القطعة من `len` تبع القطعة الأولى، مش `IMG_BYTES / عدد القطع`: القسمة
    // بتختلف عن مقاس الخادم والفرق بيتراكم لشرائط مزحلقة.
    if (seq == 0) s_chunk_size = len;
    if (s_chunk_size == 0) { unlock(); return; }
    // Only the last piece may be shorter.
    if (seq < s_expect_chunks - 1 && len != s_chunk_size) {
        ESP_LOGW(TAG, "chunk %d is %u bytes, the first was %u — refused",
                 seq, (unsigned)len, (unsigned)s_chunk_size);
        unlock();
        return;
    }

    size_t offset = (size_t)seq * s_chunk_size;
    if (offset >= IMG_BYTES || len > IMG_BYTES - offset) {
        ESP_LOGW(TAG, "chunk %d does not fit the picture — refused", seq);
        unlock();
        return;
    }

    memcpy(s_img_rx + offset, data, len);
    chunk_mark(seq);
    s_have_count++;
    s_rx_bytes += len;
    unlock();
}

bool screen_image_end(void) {
    if (!lock()) return false;
    // Check bytes too, not only the count.
    bool complete = (s_expect_chunks > 0 && s_have_count >= s_expect_chunks &&
                     s_rx_bytes == IMG_BYTES);
    if (complete) {
        uint8_t *shown = s_img;   // swap: the new picture goes on screen whole,
        s_img = s_img_rx;         // and the old buffer takes the next one
        s_img_rx = shown;
        s_want_image   = true;
        s_want_text    = false;
        s_want_dismiss = false;
        s_dirty        = true;
    }
    int have = s_have_count, want = s_expect_chunks;
    size_t bytes = s_rx_bytes;
    s_expect_chunks = 0;
    unlock();

    if (!complete) {
        ESP_LOGW(TAG, "image incomplete — %d of %d chunks, %u of %d bytes; nothing drawn",
                 have, want, (unsigned)bytes, IMG_BYTES);
        return false;
    }
    ESP_LOGI(TAG, "image complete (%d chunks)", have);
    return true;
}

#endif // ENABLE_FACE
