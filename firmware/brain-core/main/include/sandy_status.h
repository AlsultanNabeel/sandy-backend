#pragma once
#include <stdbool.h>

// Sandy's health surface — the one place that answers "why isn't she working?"
//
// The rule this enforces: **she never fails silently.** Before this existed a
// dropped Wi-Fi link, an unreachable server and a rejected handshake all looked
// identical from the outside — a face frozen mid-expression and no sound — so
// the only way to tell them apart was a serial cable. Every failure now names
// itself on her face, on the screen and (once clips are flashed) out loud.
//
// One writer, many readers: subsystems report what they observe via
// status_set(); this module owns turning that into a face, an LED state, a line
// of text and a spoken line. Subsystems must not touch the face directly for
// error conditions — that is what let a half-finished state stay on screen.

typedef enum {
    SANDY_ST_OK = 0,        // everything reachable
    SANDY_ST_BOOTING,       // still bringing subsystems up
    SANDY_ST_NO_WIFI,       // no association with the access point
    SANDY_ST_NO_SERVER,     // Wi-Fi up, the cloud is not answering
    SANDY_ST_LINK_DROPPED,  // was connected, the link died mid-conversation
    SANDY_ST_NET_SLOW,      // audio can't get out AND the radio link is weak
    // Audio can't get out and the radio is fine — a different fault wearing the
    // same symptom. Split from NET_SLOW because the old single state told the
    // owner to move closer to the router, which is useless advice when the
    // router is two metres away and the signal is strong: it sends them to fix
    // the one thing that is not broken, and makes the robot look wrong about its
    // own house.
    SANDY_ST_LINK_STALL,
    SANDY_ST_AUTH_FAILED,   // the server refused this device (config problem)
    SANDY_ST_LOW_MEMORY,    // not enough internal RAM to open a session
    SANDY_ST_COUNT
} sandy_status_t;

// Bring up the status layer. Safe before the display exists — text is queued
// and drawn once the face is ready.
void status_init(void);

// Report the current condition. Idempotent: re-reporting the same status does
// not re-announce it, so a subsystem may call this on every retry without
// making her repeat herself. Changing status always re-announces.
void status_set(sandy_status_t st);

// The current condition.
sandy_status_t status_get(void);

// True when the last reported condition is anything other than OK.
bool status_is_degraded(void);

// The Arabic line for a status — what she says out loud and what goes in the
// log. Exposed so the spoken line and the log can never drift apart.
const char *status_text(sandy_status_t st);

// The short banner drawn on the 240x240 face. Latin on purpose: the only font
// compiled into LVGL here is Montserrat, which has no Arabic glyphs and no
// shaping, so Arabic on screen would render as disconnected boxes. Arabic lives
// in the voice line above until an Arabic font is added to the build.
const char *status_banner(sandy_status_t st);
