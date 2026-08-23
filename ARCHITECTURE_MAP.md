# Sandy — architecture map

**Audience: an AI agent picking this repo up cold.** Read this before touching
anything. It is the map, not the tutorial: it tells you what exists, where it
lives, why it is shaped that way, and which parts are load-bearing.

Written by reading every source file in the repo, not from the older docs — where
this contradicts `README.md`, `docs/`, or a code comment, this is the newer
reading. Last full pass: 14 Aug 2026, kept current through 23 Aug 2026 — §2.7,
§4.5 and §4.6 rewritten for per-device broker credentials and the room node's move
onto the per-node topic tree.

**Keep this current.** When you change a contract in here — a topic, a route, an
ownership rule, a boundary — update the section as part of the same commit. A map
that lies is worse than no map.

---

## 0. What the product is

A voice-first personal assistant. She lives in a desktop robot and in phone apps.
The owner's north star, in his words: *she talks, she answers, she remembers, and
I can shape how she answers.* Everything else is secondary.

- **The robot** is her body: mics, speaker, a display that is her face, a neck
  servo, an on-board LED, and a separate camera board.
- **The apps** (iPhone, Android) are the same assistant over a different
  transport, plus the control surface for the hardware.
- **The room node** lets a user add their own devices (lights, fan, curtain, IR
  gear) so she can act on the physical world beyond her own body.

It is a **multi-tenant product**, not one person's house. Every design decision
below should be read through that lens; where the code still assumes a single
owner, it is called out as a defect, not a style.

---

## 1. Repository layout

```
cloud/                the Python backend — the brain and the API
firmware/brain-core/  ESP32-S3 robot brain (ESP-IDF, C) — voice, face, servo, MQTT
firmware/sandy_node/  the sellable pre-flashed node sketch
vision-core/          ESP32-CAM (Arduino) — camera board
sandy/                classic ESP32 (Arduino) — the room node firmware
room-node/            room controller sketch
ios/SandyApp/         SwiftUI iPhone client
android/              Kotlin + Compose client
tests/                backend tests (pytest + mongomock)
scripts/              sync, smoke test, voice-WS probe, laptop voice client
docs/                 NOT IN GIT — see §11
```

Three repos exist on the owner's Desktop; only one is worked in. See
`docs/REPOS_AND_DEPLOY.md`.

- `Desktop/Sandy-App` → **this repo**, remote `AlsultanNabeel/sandy-backend`.
- `Desktop/Nabeel/Sandy` → read-only archive of the original single-owner project.
- `Desktop/sandy-web` → the website, a separate repo, deferred.

Deploy target: Heroku app `sandy-robot-3da0693d32f7`, database `sandy-app`. The
Heroku app name is inherited from the old project; the code and data on it are
this one's. There is **no staging environment** — production is also what the
robot on the owner's desk is talking to.

---

## 2. The backend

### 2.1 Process shape

`Procfile` runs one process:

```
web: gunicorn --chdir cloud wsgi:app --workers 2 --threads 8 --timeout 120
```

Two workers × eight threads = sixteen concurrent requests. **There is no worker
dyno and no job queue.** Long work — research pipelines, image generation — runs
inside the request under a 120-second cap. If you add anything slower than that,
you are adding a queue first.

`wsgi.py` is production; `serve_api.py` is the local dev runner. Both build the
same app: `bootstrap()` → `init_runtime()` → `create_app()`. Nothing connects to
a database at *import* time — that is deliberate, and it is what lets the whole
package import in a test with no credentials. Do not add import-time side effects.

### 2.2 Directory roles

| Path | Role |
|---|---|
| `app/config.py` | Every env var the app reads, in one place. Import from here, never call `os.getenv` at a call site. |
| `app/bootstrap.py` | One-time startup: logging, quiet third-party loggers, idempotent. |
| `app/db.py` | The single Mongo handle. Every store reads through `get_db()`. |
| `app/errors.py` | Typed error taxonomy. |
| `app/agent/` | The brain: graph, nodes, tools, executor, and the memory layers. |
| `app/api/` | HTTP routes and the `/voice` WebSocket. |
| `app/features/` | Feature stores — the data layer, one module per domain. |
| `app/integrations/` | Clients for everything external. |
| `app/services/` | Push delivery and the nudge scheduler. |
| `app/utils/` | Tenancy, rate limiting, circuit breaker, profiles, text. |

### 2.3 The agent graph

`app/agent/graph/graph.py` runs a fixed pipeline:

```
fc_router → soul → router → ┬ pending  ┐
                            ├ execute  ├→ response → final reply
                            └ clarify  ┘
```

- **`agents/fc_router.py`** — one native function-calling pass. The model sees
  every registered tool as a real tool (name + description + JSON schema) and
  either calls one or more, or replies in plain text. This replaced a
  ~200-line hand-written disambiguation prompt: one call, more accurate. Mood and
  face are derived from the chosen tool by a cheap lookup, no extra model call.
  The stable prefix (tool catalogue + persona) is sent first and kept byte-identical
  across turns so Azure prompt caching keeps hitting — **do not reorder it.**
- **`nodes/soul.py`** — persona snippet, emotional context, wellness signals.
- **`nodes/router.py`** — picks the branch.
- **`nodes/execute.py`** — bridge to `ToolDispatcher`.
- **`nodes/pending.py`** — resumes a confirmation the user was mid-way through.
- **`nodes/clarify.py`** — asks instead of guessing.
- **`nodes/response.py`** — templates + persona → the reply.

State is one `TypedDict`, `graph/state.py::SandyState`, passed through every
node. No globals. Preserve that.

### 2.4 Tools

80 tools registered through `tools/setup.py::register_all_tools()` from 14 schema
modules in `agent/tools/schemas/`. `registry.py` holds them, `dispatcher.py` runs
them.

Groups: tasks · reminders · meta · other (research/image/utility) · mcp (memory +
fetch) · goals · future messages · gifts · content share · self-awareness · photos ·
brainstorm · life (shopping/habits/expenses/journal/books/reading/focus/scenes) ·
devices.

**Adding a capability means adding a tool, not editing the router.**

Destructive tools are named once, in `agent/guards.py`, and that one set is shared
by the text path and the voice path. Do not redefine it locally.

### 2.5 Memory

| Layer | Module | Store |
|---|---|---|
| Short-term conversation | `graph/graph.py` | `sandy_stm`, one doc per chat, TTL-expired |
| Facts | `agent/memory.py` | `memory` / `sandy_facts` |
| Semantic recall | `agent/semantic_memory.py` | Mongo Vector Search + OpenAI embeddings; degrades safely with no index |
| Emotional, encrypted | `agent/emotional_ltm.py` + `ltm_crypto.py` | Fernet-encrypted fields |

Around them: `interests_tracker`, `style_memory`, `lessons_memory`,
`relationships_memory`, `shared_history`, `dreams_engine`, `session_state`,
`deep_context`, `soul_vault`.

Short-term memory is on Mongo, not Redis, on purpose: the free Redis tier hit its
monthly request cap and memory silently froze. Mongo has no per-request quota and
was already wired. Don't "fix" this back to Redis without solving the quota.

### 2.6 Tenant isolation — the most important file in the repo

`app/utils/tenant_db.py`. Every data operation goes through `scoped(db, name)`,
which returns a `ScopedCollection` that stamps the caller's tenant onto every
filter and every inserted document. A caller cannot widen its own scope, even by
passing an explicit value for the tenant field — the tenant always wins.

It fails closed: `scoped()` returns `None` when there is no database **or** no
active tenant, and every store already guards `if coll is None: return <safe
default>`. So an unauthenticated context reads nothing and writes nothing.

This replaced hand-written `{"user_id": uid}` filters in every store function.
One forgotten filter there was a cross-tenant leak. **Never reintroduce a raw
collection handle on a request path.**

Index creation is the one exception: it runs on the raw handle at boot, before any
request sets a tenant. Indexes lead with `user_id`.

### 2.7 Actuation ownership

Changed 14 Aug 2026 — commit `45b956b`. Read this before touching device control.

The boundary used to ask *"is the caller the owner?"* That is the right question
for one person's house and the wrong one for a product other people buy: a second
tenant could register a device and then be refused permission to switch it on.

Now:

- **`device_store.tenant_owns_topic(topic)`** answers *"does this topic actuate a
  device in the calling tenant's registry?"* The tenant-scoped read is the
  enforcement — another tenant's topic simply is not in this tenant's collection.
- **`room_device.send_to_topic()`** gates on that. Every registry-driven path goes
  through it: the `device_control` tool, `/api/devices/<name>/control`, IR learn,
  and scene actuation.
- **`room_device.send()` / `apply_actions()`** take a device *name* and resolve the
  node from the **caller**, so a call site cannot address another tenant's room by
  getting an argument wrong — there is no argument for it. Two nodes paired is
  refused rather than guessed: guessing wrong turns off the wrong light in
  silence. The owner-only gate these used to carry came off on 23 Aug 2026 when
  the room moved under `sandy/node/<id>/room/…` (§4.5); it existed only because
  the old global strings carried no device identity.

### 2.8 Device registry

`app/features/device_store.py`. The stated principle, and it is a good one:

> Devices are **data, not code**. Each tenant owns a list. Adding a device is a
> row, never new code per device.

- Control types: `switch`, `dimmer`, `enum`, `media`, `cover`, `ir`.
- `command_payload(device, action, value)` is the **only** validator. It returns
  the payload or refuses with the list of allowed values so Sandy asks instead of
  guessing. This is what ends "turn the light on → applied the off scene".
- Transports: `{"kind":"mqtt","topic":…}`, `{"kind":"node","node_id":…,"output":…}`,
  `{"kind":"wifi_api","url":…}`.
- The `sandy/node/` namespace is **reserved** for the ownership-checked `node`
  transport. A raw `mqtt` transport is refused if it targets it — otherwise a
  tenant could aim a device at another tenant's node with a free-form topic.
- `node_store.py` is the pairing registry: `code_to_node_id(code)` is a plain
  lowercase-alphanumeric transform (not a hash), so a node flashed with its code
  derives its own topic before it is ever paired — no provisioning handshake.

### 2.8b How the robot's own parts get in there

`app/features/node_provision.py`. Added 14 Aug 2026.

A buyer should pair the robot and find her face, neck and mics already in the
Control tab. Seeding a fixed list from code would break the principle above and
would lie about any unit shipped without a servo. So **the hardware declares
itself**: the firmware publishes its outputs in every heartbeat, and
`provision_from_outputs()` maps each declared output onto a device row.

`PART_CATALOGUE` is therefore *not* a list of what exists — it is how to present
what a board reports: given output `servo`, use this label, this control type,
this range. An output the backend has not learned about is skipped, never guessed
at, so newer firmware cannot break an older backend.

Runs at two points, additively and idempotently — an owner who renames her robot's
neck keeps the name:

- `pair_node()` — for a robot paired before it was ever powered on.
- `ingest_status()` — so a firmware upgrade that adds a part appears on its own.

The heartbeat path has no tenant (it is the MQTT thread), so it enters the owner's
context using the owner id already on the node document from when that tenant
paired the code. **A heartbeat cannot nominate its own owner.**

The archive's `sandy_device.py` was deliberately *not* ported: it hardcodes global
single-owner topics, and roughly ninety per cent of it already exists here under
better names (`room_device.send_to_topic` is a generic publisher despite the name;
`mqtt_ingest` is the subscriber). Only the camera logic was genuinely missing.

### 2.9 HTTP surface

136 routes. All under `/api/*` except `/health`, `/` and `/webhook/revenuecat`.
Registered by explicit `register_*_api(app, …)` calls in `api/server.py` — there
are no Flask blueprints, so **route discovery means reading `server.py`'s
registration block**, not grepping for blueprints.

Groups: auth (password, email, Google, Apple, guest access requests) · agent (chat
+ stream) · conversations · tasks · reminders · life (shopping, habits, expenses,
journal, books, focus, scenes) · devices + nodes · memory · photos · goals · gifts ·
future messages · share · timeline · research · images · weather · persona ·
onboarding · push · subscriptions · features · daily nudge · studio plans · voice TTS.

### 2.10 Auth

`api/auth_handlers.py`. JWT, HS256. Owner tokens 7 days, guest 48 hours. Login
rate-limited to 5 attempts per 15 minutes per IP, with an in-process sliding
window as a fail-closed fallback when Mongo is down. `JWT_SECRET` has no default —
an empty secret would let anyone forge a token, so it refuses rather than degrade.

**Known dead path.** `approve_access_request()` and `deny_access_request()` are
defined and called from nowhere in the repo. They used to be invoked by the
Telegram handler, which was removed. So a visitor can `POST /api/access/request`
and poll its status, but nothing in the system can ever approve it. Either wire it
to an owner-facing endpoint or delete the whole flow — a silently disabled feature
is worse than an absent one. The module docstring still says "with a Telegram
approval flow"; that is stale.

### 2.11 External services

Routing brains, in fallback order: **Azure OpenAI** (primary) → Gemini → OpenAI
direct → a safe canned reply. A Bedrock router exists as an alternative backend.
Speech-to-text is Azure Speech. TTS is Gemini first, then Google, then Azure.
Images are Azure FLUX with an Azure OpenAI image fallback. Research is Exa; places
are Google Places. Push is APNs over HTTP/2 (`h2` is in `requirements.txt` for
exactly this). MQTT is HiveMQ Cloud over TLS.

Everything external goes through `utils/circuit_breaker.py`. A missing key
disables only its own feature — the app still boots.

---

## 3. The voice path

The highest-value and most intricate part of the system. `app/api/voice_ws/`.

```
robot mic (I2S)
  → firmware sandy_voice.c
  → wss://…/voice
  → voice_ws/session.py
      ├─ _authenticate()      HMAC handshake, ±30 s anti-replay
      ├─ speaker.py           CAM++ speaker verification (sherpa-onnx, local)
      ├─ VAD                  RMS threshold + silence + minimum utterance
      ├─ tools.py             the same tool set as the text path
      └─ memory.py            writes the turn into short-term memory
  → Gemini Live
  → audio back → speaker + amplitude-driven lip-sync
```

### 3.1 The handshake contract

Firmware sends, on connect:

```json
{"type":"hello","device_id":"<id>","ts":<unix_ms>,"hmac":"<hex>"}
hmac = HMAC-SHA256(SANDY_WS_HMAC_KEY, device_id + str(ts))
```

Server replies `{"type":"auth_ok"}` or an error frame. Error codes and what each
actually means:

| Frame | Meaning |
|---|---|
| `auth_ok` | accepted, start streaming |
| `auth_fail` | the HMAC did not match — wrong key |
| `replay` | `ts` was outside ±30 s — the **board's clock** is wrong, not the key |
| `bad_handshake` | malformed hello |
| `auth_not_configured` | the server has no `SANDY_WS_HMAC_KEY` at all |
| `owner_only` | a browser JWT that is not an owner token |

The `ts` must be wall-clock, so the firmware blocks on SNTP before it can connect.
A board that cannot reach a time server will sit there forever while the wake word
keeps working — that failure looks exactly like a dead network.

Three ways in, checked in this order: a legacy plain-text secret (dev/echo tests),
a browser JWT (`{"type":"hello","token":…}`, owner only — live voice is the owner
experience), then the device HMAC. With no key configured at all it refuses unless
`SANDY_WS_ALLOW_OPEN=1`, so a missing env var in production cannot leave the
socket open.

You can probe all of this from a browser without hardware — see §10.

### 3.2 Speaker verification

`features/speaker_id.py` + `voice_ws/speaker.py`. CAM++ via sherpa-onnx, running
locally: no account, no torch. Gated by `SANDY_REQUIRE_SPEAKER_AUTH=1`, off by
default, and it only guards the sensitive tool set (`task_delete`,
`reminder_delete`, `calendar_delete`, `schedule_message_to_self`). With no
voiceprint enrolled it allows — it does not lock the owner out before enrolment.

---

## 4. The firmware — robot brain

`firmware/brain-core/`, ESP-IDF, ESP32-S3. `sandy_voice.c` is 1400 lines and is
where the difficulty lives.

| File | Does |
|---|---|
| `sandy_main.c` | boot order; each init wrapped in `TRY_INIT` so one failure never boot-loops the board |
| `sandy_voice.c` | wake word, local commands, VAD, AEC, the WS link, the uplink buffer, the session manager |
| `sandy_face.c` | LVGL face — 25 moods, blink/drift/doze animations, focus ring, status banner |
| `sandy_status.c` | **the health surface** — see §4.2 |
| `sandy_mqtt.c` | command subscriptions + status publish |
| `sandy_wifi.c` | association; power save is explicitly **off** (`WIFI_PS_NONE`) for real-time audio |
| `sandy_led.c` `sandy_servo.c` `sandy_buzzer.c` `sandy_motors.c` `sandy_sensor.c` `sandy_touch.c` `sandy_ears.c` `sandy_mic.c` `sandy_spktest.c` `sandy_ota.c` `sandy_nvs.c` `sandy_remote.c` | peripherals, OTA, remote log |

### 4.1 The session lifecycle

The paid cloud link is open **only** between a wake word and the silence after it.

1. Wake word detected locally (`Hi Andy`) → buzzer cue, `MOOD_CURIOUS`, `s_wake_req`.
2. Session manager frees the ~70 KB MultiNet command model **before** opening the
   socket — its internal SRAM is exactly what the TLS task needs. This ordering
   was a real deadlock once; do not reverse it.
3. `ws_open()` → hello → `auth_ok` → `MOOD_FOCUSED`, streaming.
4. Silence for `VOICE_SESSION_IDLE_MS` (8 s) → close, reload the command model,
   back to idle.
5. Link lost mid-call → `VOICE_RECONNECT_GRACE_MS` (15 s) of grace before hanging
   up, so a blip does not end a sentence.

Every session gets a fresh `esp_websocket_client_init` and ends with a full
`destroy` — reusing the handle once wedged the link until reboot.

### 4.2 Failure reporting — `sandy_status.c`

Added 14 Aug 2026 because **she had no way to report anything**. No Wi-Fi, an
unreachable server, a refused handshake and an out-of-memory open all looked
identical from the outside: a frozen face and silence, diagnosable only with a
serial cable.

One table maps each condition to a face, an LED state, a Latin banner drawn across
the bottom of the display, and the Arabic sentence she will speak once clips are
flashed: `OK`, `BOOTING`, `NO_WIFI`, `NO_SERVER`, `LINK_DROPPED`, `NET_SLOW`,
`AUTH_FAILED`, `LOW_MEMORY`.

Rules:
- **Subsystems must not set the face directly for error conditions.** Call
  `status_set()`. Direct face writes are how a half-finished state stayed on screen.
- `status_set()` is idempotent — re-reporting the same condition does not
  re-announce, so retry loops don't make her repeat herself.
- The banner is Latin because Montserrat is the only font in this build and has no
  Arabic glyphs or shaping. Arabic lives in the spoken line. Adding an Arabic font
  is the fix, and it is not done.
- Voice clips are **not** flashed yet — the partition table has no room reserved.
  `status_set()` has the hook and the sentences; the audio is the missing piece.

### 4.3 The uplink — why it is buffered

Fixed 14 Aug 2026, commit `caaefb9`. Diagnosed from a serial capture, and the
previous two hypotheses (heap exhaustion, then a missing server key) were both
wrong — check the log before theorising here.

What the log showed: auth succeeded, streaming began, and ~1.1 s later a single
socket write timed out — `transport_poll_write(0)`, `errno=0`, no TLS error. Pure
backpressure. `esp_websocket_client` treats that as a dead transport, tears the
connection down and waits 5 s to reconnect. Her listening window is 8 s. So one
slow second ended the call. The link in question stalls constantly — the capture
is a continuous `DELBA reason:39` storm from the access point.

The cause was structural: the mic loop wrote straight to the socket with one
second of patience, which is the most a real-time capture loop can ever afford.

Now: `mic_send()` writes into a 128 KB PSRAM stream buffer (~4 s of 16 kHz 16-bit
mono) and returns immediately, dropping the newest audio if full. `ws_tx_task`
(priority 6, below the audio pair at 8/9) drains it with 4 s of patience, which it
can afford because nothing real-time waits on it. A backlog past half the buffer
raises `SANDY_ST_NET_SLOW`. The buffer is reset on session close so the tail of
one call never opens the next.

### 4.4 The frozen-face bug, for the record

The wake word set `MOOD_CURIOUS` immediately, and the **only** code that cleared it
lived in the session-close branch — which requires a session that opened. So a
failed `ws_open()` left her staring, awake-looking and deaf, until a power cycle.
That branch now names the reason (`NO_WIFI` / `LOW_MEMORY` / `NO_SERVER`) and
returns to idle. If you add another early-return path, clear the face on it.

### 4.5 MQTT topics — the current contract

Moved to the per-node namespace 14 Aug 2026 — commit `061cf82`. The room node
followed on 23 Aug 2026; **nothing global is left.** All three boards are flashed
and verified on this tree.

```
sandy/node/<node_id>/mood · servo · buzzer · base · led · autonomous · focus · ota
sandy/node/<node_id>/mic_l · mic_r                 mute (payload "on" = unmuted)
sandy/node/<node_id>/mic_l_gain · mic_r_gain       digital gain, 0..300
sandy/node/<node_id>/volume · speaker_test · noise
sandy/node/<node_id>/status                        heartbeat → ingest_status
sandy/node/<node_id>/ir/learned                    captured IR code
sandy/node/<node_id>/cam/command · snapshot · status · event
sandy/node/<node_id>/room/light · music            room node commands
sandy/node/<node_id>/room/status                   room heartbeat → ingest_status
```

`node_id` is derived on the board from `SANDY_PAIR_CODE` in `secrets.h` using the
**same transform as `node_store.code_to_node_id`** — lowercase, alphanumerics
only. Keep those two in lockstep; if one drifts the robot goes quiet and nothing
says why. Deriving rather than provisioning means the board knows its own topics
on first boot, before it has ever been paired.

The brain subscribes with a single wildcard (`sandy/node/<id>/#`) and dispatches on
the suffix, so adding a control cannot be half-done by forgetting a subscription.

The heartbeat carries `capabilities`, `outputs`, `firmware_version`, live per-mic
levels, and the current gain/mute/volume/noise settings. **Those three key names
are the backend's spelling** — `mqtt_ingest` reads them exactly and silently
ignores anything else.

#### Three boards, one node id

The brain, the camera and the room node share a pairing code and therefore a node
id: they are one robot, not three boxes. Each writes in its own **namespace** —
the camera under `cam/`, the room node under `room/`, the brain in the bare one —
and each has its own heartbeat topic, because `+` matches a single level and
`sandy/node/+/status` never sees `…/cam/status` or `…/room/status`. A board whose
heartbeat topic nobody subscribes to works perfectly and is invisible: it obeys
commands and never appears in the app, because what registers a device is the
board *declaring an output*.

`node_store._merge_outputs` replaces only the namespaces the arriving heartbeat
speaks for. It was a boolean (camera or not) until 23 Aug 2026, which was correct
with two boards and silently wrong with three — the room's outputs read as "not
camera", so brain and room heartbeats deleted each other five seconds apart, for
ever. A heartbeat declaring nothing keeps everything: silence is not a claim that
the hardware is gone.

Declared `kind` values must be in `node_store.KNOWN_CAPABILITIES`. Anything else
is dropped **silently** — the board publishes, the server parses, the entry
vanishes, and the app is simply missing a lamp with no error anywhere.

#### Broker credentials

Every board used to ship with one shared broker login compiled in, so any customer
could subscribe to any other customer's topics. Since 23 Aug 2026 each board has
its own, and the shared one is deleted.

The brain is handed its credential **on the voice handshake** (`voice_ws/session.py`
→ `broker_creds.creds_for_device`), stores it in NVS and applies it live. Not over
the broker, deliberately: delivering a broker credential over the broker would
mean the shared login has to keep working for ever, which is the thing being
retired. The voice socket authenticates against a different key, so it still works
after the shared login is revoked — that is what makes revoking it possible.

The camera and the room node have no voice link and take theirs from their own
`secrets.h` at flash time. Issuing is a config table (`SANDY_BROKER_CREDS`) rather
than an API call because programmatic issuing needs the broker's paid plan;
`creds_for_device` is the seam where that swaps in.

The client id is derived from the node id. It was fixed for every brain until
23 Aug 2026 — and a broker allows one connection per id, dropping the older, so
two robots kicked each other off in a loop that never settles regardless of whose
credential each was using. Per-device credentials do not help with that; only the
id does.

**The backend is a broker client too**, and the easy one to forget. `mqtt_ingest`
and `room_device` connect with `SANDY_MQTT_USER` / `SANDY_MQTT_PASS`, and unlike a
board the server is not scoped to one node — it listens to every tenant's
heartbeats and publishes to every tenant's devices, so its filter is `sandy/node/#`.
Revoking the shared credential without repointing those two vars cuts the server
off the broker, and the symptom is not an error: heartbeats stop arriving, every
node reads offline, and no device is ever provisioned — because what registers a
device is a heartbeat.

**One topic filter per board.** The free broker plan gives a credential exactly one
permission, which is the other reason the room had to leave the global tree: the
brain needed its own subtree *and* the global one, and that is not expressible.
Steps to issue the credentials live in `docs/مفاتيح-الوسيط.md` (untracked — `docs/`
is gitignored).

### 4.6 Hardware reality — read before promising a control surface

Updated 23 Aug 2026. `docs/HARDWARE_CAPABILITIES.md` is now **stale in two places**
and this table supersedes it: it claims `mood` accepts only six values (the
firmware's `MOOD_MAP` has always carried all 25) and it lists the mics and speaker
as unexposed (they now have controls).

| Part | Reachable from the backend | Physically working |
|---|---|---|
| Camera (ESP32-CAM) | Yes — flash, snapshot, stream, framesize, quality | Yes — `vision-core/`, flashed and on the broker |
| Face / display | Yes — all 25 moods | Yes |
| Microphones | Yes — per-channel gain, mute, live level | Yes |
| Speaker | Yes — volume 0..100, test tone | Yes, through the voice path |
| Noise suppression | Yes — off / mild / medium / aggressive | Yes |
| On-board LED | Yes — off / idle / listening / talking | Yes |
| Neck servo | Yes | **Not physically wired yet** |
| Base motors | Topic exists | `ENABLE_MOTORS = 0` |
| Buzzer, distance sensor | Yes | Dropped by decision; flags still `1` |
| Room light (room node) | Yes — `room/light`, provisioned from its heartbeat | Yes — servo presses the wall switch |
| Room music (room node) | Yes — `room/music`, stop/pause/resume/next/prev | Yes — DFPlayer over UART2 |

"Mute the left mic, speak, and watch only the right meter move" now works end to
end — that is the point of per-channel metering, and it is how you tell a dead mic
from a cross-wired one without a multimeter.

**Everything in the first column is true of the source, not of the board on the
desk, until it is flashed.**

The camera board program is no longer missing — `vision-core/` exists, is
flashed, and answers on the broker. Still genuinely missing: the **IR board
code** (the server side is complete: learn topic, endpoint, device type — only
the sketch is unwritten, and it is the cheapest large feature left), servo easing
(it jumps, which is most of what makes the motion look cheap), and two-mic
beamforming.

The Arabic display font is done: `main/fonts/` now carries the typeface at
twenty-four and thirty-two pixels alongside LVGL's built-in sixteen, which is
what makes the text-size control real rather than decorative.

---

## 5. The other boards

- **`vision-core/`** (ESP32-CAM) — **this directory does not exist.** It is
  named here, in `README.md` and in `docs/Claude.md`, and it was described in
  this file as "fully working on the bench" — none of which was ever true.

  Everything the camera needs on *our* side is written and tested: the command
  channel, the chunked-snapshot reassembly in `camera_client.py`, the `cam/`
  telemetry namespace, six catalogue parts, and a viewer screen in the app.
  The board program those talk to was never written.

  This is why the camera has never worked once, through every fix aimed at it:
  the snapshot request is published correctly to `sandy/node/<id>/cam/command`
  and nothing is subscribed; no `cam/status` heartbeat is ever sent, so the
  address the live view needs never arrives, and "couldn't get the address" was
  the exact truth. Each of those symptoms was read as a bug in the plumbing and
  the plumbing was fine.

  A stock `CameraWebServer` sketch flashed to the board would serve
  `http://<ip>/stream` — so the live view would work the moment the address is
  known by some other means — but it speaks no MQTT, so it can never announce
  that address itself and cannot answer a snapshot request.

  What it must do, to match what is already built:
  `app/integrations/camera_client.py` (added 14 Aug 2026) is the backend half:
  it publishes the request, holds the pieces, and hands back one JPEG.
  The sketch moved onto `sandy/node/<id>/cam/*` in the same session: it derives
  its `node_id` from `SANDY_PAIR_CODE` in its own `secrets.h`, which must be
  **flashed with the same code as its robot's brain** — that is what makes the two
  boards one node instead of two things to pair. Topics are built once in
  `setupMQTT()` before any subscribe, because empty topics would leave the board
  publishing into `sandy/node//cam/...` and looking healthy while nobody hears it.
- **`sandy/`** (classic ESP32) — the room node.
- **`room-node/`**, **`firmware/sandy_node/`** — the room controller and the
  sellable pre-flashed node.

---

## 6. iPhone app

`ios/SandyApp/`, SwiftUI, ~21 000 lines, 26 feature folders. Swift is one module,
so folders are organisation only.

- `App/` — `SandyApp`, `AppState` (holds the base URL), `MainTabView`.
- `Core/Networking/` — `APIClient` split into 16 extensions by domain, behind
  `APIClientProtocol`. **Add new endpoints as an extension, not to the base class.**
- `Core/Auth/` — Keychain (`…ThisDeviceOnly`), Google sign-in, auth view.
- `Core/Intents/` — App Intents / Siri shortcuts, including device intents.
- `Core/Stores/LoadableStore.swift` — the shared load/error/empty state machine.
- `Services/` — `GeminiLiveManager` (in-app live voice), `SpeechManager`,
  `NotificationManager`, `SubscriptionManager`.
- `Localization/` — one `L10n+<Area>.swift` per feature. Arabic/English, RTL/LTR.
- `Widgets/` — home-screen widgets.

Sync to the Xcode build copy with `scripts/sync_ios.sh` (rsync, `--delete`). The
build copy lives at `~/Desktop/SandyApp/SandyApp`, which is why that folder must
not be renamed. Build from the Xcode GUI — `xcodebuild` on the CLI hangs on the
iCloud-synced folder.

**Housekeeping:** five empty `… 2` folders (`Core 2`, `Services 2`, `Features 2`,
`Widgets 2`, `Localization 2`) are Finder duplication leftovers. Untracked, empty,
safe to delete.

---

## 7. Android app

`android/`, Kotlin + Compose, ~4 000 lines. Foundation stage — the shell is built
and features are mounted into tabs one at a time. Present: auth, home, daily
(tasks, reminders, habits, focus), life (expenses, journal), Sandy hub + chat,
onboarding. `data/ApiClient.kt` is the whole networking layer.

The gap between iPhone (26 features) and Android (about 8) is the largest
inconsistency in the product.

---

## 8. Data model

47 Mongo collections, all reached through `scoped()`. 45 carry the `sandy_`
prefix; two predate it (`memory`, `guest_usage`) and key on `chat_id` rather than
`user_id` — pass `field=` to `scoped()` for those.

Identity and access: `sandy_users`, `sandy_auth`, `sandy_active_user_profile`,
`sandy_usage_daily`, `sandy_usage_rl`, `guest_usage`.
Conversation and memory: `sandy_stm`, `sandy_conversations`, `sandy_facts`,
`memory`, `sandy_memories`, `sandy_vector_index`, `sandy_context_metadata`,
`sandy_session_state`, `sandy_pending_state`, `sandy_state`.
Productivity: `sandy_tasks`, `sandy_reminders`, `sandy_goals`, `sandy_focus`,
`sandy_focus_meta`, `sandy_brainstorms`, `sandy_bs_pending`.
Life: `sandy_shopping`, `sandy_habits`, `sandy_habit_log`, `sandy_expenses`,
`sandy_journal`, `sandy_books`, `sandy_reading_sessions`, `sandy_reading_meta`.
Hardware: `sandy_devices`, `sandy_nodes`, `sandy_scenes`, `sandy_scene_timers`,
`sandy_voiceprints`, `sandy_face`.
Social and delivery: `sandy_photos`, `sandy_photo_files`, `sandy_gifts`,
`sandy_shared_content`, `sandy_future_messages`, `sandy_push_tokens`,
`sandy_daily_nudge`, `sandy_nudge_locks`, `sandy_activity`, `sandy_evals`.

Indexes lead with `user_id` and are created at boot on the raw handle.

---

## 9. Tests and CI

35 test files, pytest + mongomock, no hardware and no live credentials needed.
`tests/test_device_system.py` carries the headline guarantee: the brain may only
act on a **registered** device with a **validated** action, and refuses with the
allowed list rather than guessing.

CI (`.github/workflows/tests.yml`): pytest with coverage → Codecov → `bandit -ll`
→ `ruff check` → a secret scan that fails the build if a `.env`, key, or
service-account JSON is ever tracked.

**CI does not build iOS, Android, or the firmware.** Twenty-one thousand lines of
Swift have no build gate.

Running the backend tests needs `pyOpenSSL>=23.2.0` alongside `pymongo`, or
collection dies on an OpenSSL symbol mismatch.

---

## 10. Diagnosing without hardware

The sandbox proxy blocks raw WebSocket and non-allowlisted HTTPS, but a **browser**
can reach the deployed app. Open any page on the Heroku origin and run JS:

```js
const ws = new WebSocket("wss://<app>.herokuapp.com/voice");
ws.onopen    = () => ws.send(JSON.stringify({type:"hello",device_id:"probe",ts:Date.now(),hmac:"00"}));
ws.onmessage = e  => console.log(e.data);
```

The reply distinguishes every failure mode in the table in §3.1 — including
whether the server has a key configured at all — without touching the robot.

To prove the board's own key works, compute the HMAC where the secret lives
(never paste it into a browser), generate candidate timestamps a little in the
future, and have the page pick the one nearest its own clock.

**Serial log:** `Desktop/سجل-ساندي.command` on the owner's machine. On macOS the
port must be opened *before* `stty` is applied and read from that same descriptor
— `cat` reopening the port resets the termios settings and you get garbage.

---

## 11. Conventions and hard rules

From `CONVENTIONS.md` and the owner's standing instructions:

- **Never `git push` and never deploy.** Commit locally and say it is ready.
- Removals must be complete — no dead code, no orphan imports, no stale wiring.
- No `except Exception: pass`. Catch the narrowest exception; broad catches only
  at true boundaries (background thread, request handler, external call).
- One `logger = logging.getLogger(__name__)` per module, area-prefixed messages
  (`[router]`, `[auth]`, `[voice]`), lazy `%s` formatting, never `print`.
- All fire-and-forget work goes through `utils/thread_pool.submit_background`.
  Raw `threading.Thread` is not allowed for it (long-lived loops and the MQTT
  listener are exempt).
- Docs and commit messages in English. Conversation with the owner in Arabic.
- **`docs/` is excluded by `.gitignore`.** Everything in it — the deploy map, the
  hardware inventory, the audit plan, the analysis — exists only on the owner's
  machine and never reaches GitHub. This file lives at the repo root deliberately,
  so it survives a fresh clone.

## 12. Known defects, ranked

Updated 14 Aug 2026.

1. **Nothing written today is on the robot.** The firmware changes — uplink
   buffer, status layer, per-node topics, mic and speaker control, noise
   suppression — are source only. **They were never compiled**: this work was done
   in an environment with no ESP-IDF toolchain. Run `idf.py build` before the
   first flash and expect to fix build errors. Everything in §4 describes the
   source, not the board.
2. **No control page.** The backend surface and the firmware controls both exist
   now; the iPhone screen that drives them does not. It should read
   `/api/devices` and render by `control_type`, with **no robot-specific code** —
   that is what makes it work for a Tuya plug tomorrow.
3. **Visitor approval path is dead code.** §2.10.
4. **No error tracking in production.** Sentry, Langfuse and the metrics modules
   were never ported from the archive. Failures are discovered by the user — which
   is exactly how the voice bug was found.
6. **No staging environment.** Production is what the robot on the desk talks to. §1.
7. **No CI gate for iOS, Android or firmware.** §9. The firmware gap is the one
   that bit today.
8. **The room node is still on global topics**, which is the last thing keeping
   `room_device.send()` owner-only. §2.7.
9. **Stale in-code documentation.** `feature_flags.py` advertises three flags for
   subsystems that do not exist here (Anthropic prompt caching — the SDK is not
   even a dependency; DSPy; Telegram feedback buttons) and describes Sandy as a
   3–4 user family app, which contradicts the product. `auth_handlers.py`'s
   docstring still mentions Telegram. `docs/HARDWARE_CAPABILITIES.md` is stale on
   moods, mics and the speaker — see §4.6.
10. **Android is far behind iOS.** §7.
11. **Servo motion is a jump, not a move.** ~30 lines of easing, and it is most of
    the difference between looking like a product and looking like a prototype.
12. **The display has no Arabic font.** LVGL ships
    `LV_USE_ARABIC_PERSIAN_CHARS`; until it is enabled with a font that has the
    glyphs, her status banner has to be Latin. §4.2.
