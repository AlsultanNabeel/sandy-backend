#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Owner's text or picture over the face; stays until dismissed, then the face returns.
// Images arrive as raw 240×240 RGB565 (no decoder on the board), chunked over MQTT
// like camera snapshots, reassembled in PSRAM to keep internal RAM for voice.

#define SCREEN_W 240
#define SCREEN_H 240

// NULL or empty takes the message down. Arabic and English both render.
// ثلاث مقاسات، كلها خطوط مولّدة فعليًا (main/fonts).
typedef enum {
    SCREEN_SIZE_SMALL = 0,
    SCREEN_SIZE_MEDIUM,
    SCREEN_SIZE_LARGE,
} sandy_screen_size_t;

void screen_show_text(const char *text);

// Setup QR with a caption; caption only on builds without the QR widget.
void screen_show_qr(const char *payload, const char *caption);

// Applies to this and later lines, immediately if something is showing.
void screen_set_size(sandy_screen_size_t size);

// small / medium / large; anything else = medium.
sandy_screen_size_t screen_size_from_name(const char *name);

// Abandons any transfer in progress. False if the buffer could not be taken.
bool screen_image_begin(int total_chunks);

// `seq` is 0-based, data already base64-decoded. Out-of-range or duplicate
// pieces are ignored (broker input is untrusted).
void screen_image_chunk(int seq, const uint8_t *data, size_t len);

// False (and logs which) if pieces are missing.
bool screen_image_end(void);

void screen_dismiss(void);

// Called only by sandy_face on the LVGL task, so all LVGL calls stay on one task.
struct _lv_obj_t;
void screen_lvgl_build(struct _lv_obj_t *parent);
void screen_lvgl_tick(void);
