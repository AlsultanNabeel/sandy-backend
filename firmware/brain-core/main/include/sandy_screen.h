#pragma once
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

// Putting something of the owner's on Sandy's display, over her face.
//
// Two things can go up: a line of text typed in the app, or a picture sent from
// it. Both cover the face completely and both stay until they are taken down —
// no timeout. A note that vanishes on its own is not a note, and a reminder you
// have to catch is worse than none.
//
// Her face is not lost while a message is up; it is underneath, and dismissing
// brings it straight back with whatever mood it had.
//
// ── The image path, and why it is shaped this way ────────────────────────────
//
// The panel is 240×240 RGB565: 115,200 bytes. Two decisions follow from that.
//
// The board does not decode anything. No JPEG, no PNG — the backend resizes and
// converts, and what arrives here is raw pixels in exactly the layout the panel
// wants. A decoder would cost internal RAM this board does not have, and would
// mean an image could fail on the one device the owner cannot debug.
//
// And it arrives in pieces. 115 KB does not fit in an MQTT message, so the
// backend chunks it and this reassembles — the same shape the camera already
// uses to send snapshots the other way, deliberately, so there is one pattern
// to understand rather than two.
//
// The buffer lives in PSRAM. Internal RAM is what the voice session needs, and
// a picture must never be the reason she cannot talk.

#define SCREEN_W 240
#define SCREEN_H 240

// A line of text. NULL or empty takes the message down. Arabic and English both
// render; the font and the right-to-left handling are set in sdkconfig.
void screen_show_text(const char *text);

// ── Image transfer ───────────────────────────────────────────────────────────

// Start a new image. `total_chunks` is how many pieces to expect. Any transfer
// already in progress is abandoned — the newest request is the one the owner is
// waiting on. Returns false if the buffer could not be taken.
bool screen_image_begin(int total_chunks);

// One piece, at `seq` (0-based), already base64-decoded. Out-of-range or
// duplicate pieces are ignored rather than trusted: this arrives over a shared
// broker, so it is input, not instruction.
void screen_image_chunk(int seq, const uint8_t *data, size_t len);

// All pieces in? Draw it. Returns false if pieces are missing, and says which
// in the log rather than showing a half-painted picture.
bool screen_image_end(void);

// Take whatever is up down and give the face back.
void screen_dismiss(void);

// Is a message currently covering the face?
bool screen_is_showing(void);

// ── Called by sandy_face only, on the LVGL task ──────────────────────────────
//
// These two exist so that every LVGL call in the whole display lives on one
// task. sandy_face owns the LVGL context and its timers; it builds this panel
// as a child of the same screen and ticks it from the same timer loop. Nothing
// else may call them.
struct _lv_obj_t;
void screen_lvgl_build(struct _lv_obj_t *parent);
void screen_lvgl_tick(void);
