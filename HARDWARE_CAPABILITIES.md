# Sandy — hardware capability inventory

Every control the hardware actually exposes, so the manual control page in the
web app can be built without guessing. Written straight from the firmware, not
from memory. Two boards:

- **brain** — ESP32-S3, `firmware/brain-core/`, talks MQTT under `sandy/cmd/*`
- **vision** — ESP32-CAM, `vision-core/`, talks MQTT under `sandy/cam/*` plus a
  local HTTP server

The last section lists things the hardware can do that **nothing can reach yet** —
read it before designing the page, those are the holes worth filling.

---

## Display (ST7789, on the brain)

Sandy's face. Wired and verified.

| Control | Values | Reachable via |
|---|---|---|
| Mood / expression | 26 moods (below) | `sandy/cmd/mood` |
| Look direction | left / right / center, per-axis angles | firmware only — **not exposed** |
| Focus overlay | on / off | firmware only — **not exposed** |
| Iris colour | any RGB | firmware only — **not exposed** |
| Backlight | PWM dimming on GPIO1 | firmware only — **not exposed** |

The 26 moods:

```
idle, happy, big_happy, excited, playful, silly, proud, grateful, hopeful,
love, shy, calm, curious, thinking, focused, alert, surprised, confused,
worried, disappointed, sad, grumpy, angry, bored, sleepy
```

`sandy/cmd/mood` currently accepts a shortlist only: `happy`, `sad`, `curious`,
`alert`, `error`, `boot`. The other twenty are unreachable from outside.

---

## Microphones (2x INMP441, on the brain)

Wired and verified — wake word detected, voice session opened, speaker verified.

| Capability | State | Notes |
|---|---|---|
| Wake word | working | `Hi Andy`, local, no cloud |
| Local command words | working | 15 phrases, listed below |
| Voice session to the cloud | working | opens on wake word |
| Speaker verification | working | tells Sandy it's really Nabeel |
| Echo cancellation | on | so she can be interrupted while talking |
| Sound direction (turn toward the speaker) | **hardware ready, not implemented** | needs the stereo slots read separately |
| Mic gain / sensitivity | fixed in firmware | **not exposed** |

The 15 local phrases (7 act with no cloud at all, 8 just open a voice session):

```
SANDY TURN ON THE LIGHT        → room/cmd/light on
SANDY TURN OFF THE LIGHT       → room/cmd/light off
SANDY TURN ON THE FAN          → room/cmd/fan on
SANDY TURN OFF THE FAN         → room/cmd/fan off
SANDY PLAY MUSIC               → room/cmd/music on
SANDY TURN OFF MUSIC           → room/cmd/music off
SANDY TURN EVERYTHING OFF      → light + fan + music off
SANDY WHAT TIME IS IT          → opens voice session
SANDY GOOD MORNING             → opens voice session
SANDY LETS READ                → opens voice session
SANDY LETS WORK                → opens voice session
SANDY LETS START WORKING       → opens voice session
SANDY LETS THINK TOGETHER      → opens voice session
SANDY I WANT TO SLEEP          → opens voice session
HEY SANDY                      → opens voice session
```

---

## Neck servo (SG90, on the brain)

Not wired yet. Firmware exposes one thing only.

| Control | Values | Reachable via |
|---|---|---|
| Angle | 0–180 degrees | `sandy/cmd/servo` |
| Speed / easing | — | **not implemented** |
| Sweep / scan pattern | — | **not implemented** |
| Return-to-centre | — | **not implemented** |

A control page wants a slider plus preset buttons (left / centre / right). Speed
control matters for panoramas: the camera needs the neck to stop moving before
each shot.

---

## Speaker + amp (MAX98357A, on the brain)

Not wired yet. Audio comes from the cloud voice session; there is no local
"play this tone" control.

| Control | State |
|---|---|
| Voice playback | working through the voice session |
| Volume | **not exposed** — fixed |
| Local test tone | **not implemented** |
| Mute | **not exposed** |

---

## On-board RGB LED (on the brain)

| Control | Values | Reachable via |
|---|---|---|
| State | off / idle (blue) / listening (white) / talking (amber) | firmware only — **not exposed** |
| Arbitrary colour | any RGB | **not implemented** |

Driven automatically by the voice session. A control page could use manual
override as a "find the robot" or notification light.

---

## Camera (ESP32-CAM, separate board)

Fully wired, flashed and verified on the bench. This is the most complete part —
everything below was tested working.

### Commands — publish JSON to `sandy/cam/command`

| Command | Payload | Does |
|---|---|---|
| `flash` | `state: on/off`, `level: 0-255`, `ms: <auto-off>` | white LED on/off at a brightness, with a safety timer |
| `flash_mode` | `mode: off/on/auto` | `auto` fires the flash only when the sensor's gain says the room is dark |
| `snapshot` | `id`, `settle_ms: 0-3000`, `flash: off/on/auto` | one photo, published in chunks. `settle_ms` waits for the image to stabilise after the neck moves |
| `burst` | `count: 1-24`, `interval_ms: >=200`, `id` | repeated shots — this is the panorama primitive |
| `set` | any settings below, `save: 0/1` | change settings live; saved to flash by default |
| `get` | — | publishes every current setting to `sandy/cam/status` |
| `stream` | `state: on/off` | starts the HTTP video server, replies with the URL |
| `save` | — | persist current settings |
| `defaults` | — | wipe saved settings, back to factory |
| `reboot` | — | restart the board |

### Sensor settings — all live, all persisted

| Setting | Range | Setting | Range |
|---|---|---|---|
| `framesize` | `96X96`…`UXGA` (0–13) | `aec` | 0–1 |
| `quality` | 4–63 (lower = better) | `ae_level` | -2–2 |
| `brightness` | -2–2 | `aec_value` | 0–1200 |
| `contrast` | -2–2 | `agc` | 0–1 |
| `saturation` | -2–2 | `agc_gain` | 0–30 |
| `sharpness` | -3–3 | `gainceiling` | 0–6 |
| `denoise` | 0–8 | `bpc` | 0–1 |
| `special_effect` | 0–6 | `wpc` | 0–1 |
| `wb_mode` | 0–4 | `raw_gma` | 0–1 |
| `awb` | 0–1 | `lenc` | 0–1 |
| `awb_gain` | 0–1 | `hmirror` | 0–1 |
| `aec2` | 0–1 | `vflip` | 0–1 |
| `dcw` | 0–1 | `colorbar` | 0–1 |

Frame size names: `96X96`, `QQVGA`, `QCIF`, `HQVGA`, `240X240`, `QVGA`, `CIF`,
`HVGA`, `VGA`, `SVGA`, `XGA`, `HD`, `SXGA`, `UXGA`.

### HTTP endpoints (local network only)

| Route | Returns |
|---|---|
| `/still` | one JPEG, immediately |
| `/stream` | MJPEG video |
| `/status` | JSON health |

Off by default; `stream` turns the server on, and it stops itself when nobody is
watching. Video cannot go over MQTT — too slow and it floods the broker — so any
live-view UI must hit these routes directly.

### Feedback topics

| Topic | Carries |
|---|---|
| `sandy/cam/status` | health + every setting, every 10s and on demand |
| `sandy/cam/snapshot` | image chunks (base64 JSON) |
| `sandy/cam/event` | command acks, capture errors, completion |

---

## Robot body — wired but disabled in firmware

| Part | Topic | Flag state |
|---|---|---|
| Base motors (L298N) | `sandy/cmd/base` — forward / backward / left / right / stop | `ENABLE_MOTORS = 0` |
| Focus session signals | `sandy/cmd/focus` — start / break / end | working |
| Autonomous mode | `sandy/cmd/autonomous` | working |
| OTA trigger | `sandy/cmd/ota` | `ENABLE_OTA = 0` |
| Buzzer | `sandy/cmd/buzzer` | dropped by decision, flag still `1` — **needs turning off** |
| Distance sensor | — | dropped by decision, flag still `1` — **needs turning off** |

---

## The holes worth filling before the control page

Ranked by how much they'd add:

1. **Servo speed and sweep.** Without it, panoramas jerk and the camera shoots
   blurred frames. The camera side already has `settle_ms` waiting for it.
2. **All 26 moods over MQTT.** The face can do 26, the cloud can ask for 6.
3. **Look direction and iris colour.** Cheap to expose, and they're the
   difference between a face that stares and a face that pays attention.
4. **Speaker volume.** Currently fixed, which is awkward at night.
5. **Manual LED override.** Useful as a notification channel.
6. **Sound direction from the two mics.** The hardware is in place; this is the
   feature that makes her turn toward whoever is speaking.
7. **Crash and brownout reporting.** Agreed during bring-up, not built yet: reset
   reason, core dump, brownout detection and heap alerts pushed to Telegram so a
   failure explains itself instead of being guessed at.
