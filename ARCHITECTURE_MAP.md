# Sandy — architecture map

**Audience: an AI agent picking this repo up cold.** Read this before touching
anything. It is the map, not the tutorial: it tells you what exists, where it
lives, why it is shaped that way, and which parts are load-bearing.

Written by reading every source file in the repo, not from the older docs — where
this contradicts `README.md`, `docs/`, or a code comment, this is the newer
reading. Last full pass: 14 Aug 2026. The backend sections (§2, §3.2, §8, §9,
§12) were rewritten on **30 Sep 2026** for phase 5 of the rebuild, which deleted
the old agent (graph, router, 80-tool registry, memory layers), every
per-feature store and route the app stopped calling, and the scene-timer runner.
What is described below is what exists; the old world is in git history.

**§12 is the list of what is still wrong**, ranked by whether a customer can
feel it.

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
- **The app** (iPhone) is the same assistant over a different transport, plus
  the control surface for the hardware. Android is deferred — §7.
- **The room node** lets a user add their own devices (lights, fan, curtain, IR
  gear) so she can act on the physical world beyond her own body.

It is a **multi-tenant product**, not one person's house. Every design decision
below should be read through that lens; where the code still assumes a single
owner, it is called out as a defect, not a style.

---

## 1. Repository layout

```
cloud/                the Python backend — the brain and the API
firmware/             every board's program, one folder each:
  brain-core/         ESP32-S3 robot brain (ESP-IDF, C) — voice, face, servo, MQTT
  vision-core/        ESP32-CAM (Arduino) — camera board
  room-node/          classic ESP32 (Arduino) — the room node (sandy/node/<id>/room/*)
ios/SandyApp/         SwiftUI iPhone client
tests/                backend tests (pytest + mongomock)
scripts/              migration into the blocks, voice-WS probe, board provisioning,
                      firmware keygen/publish, CA-roots and hardware-doc generators, C checks
docs/                 NOT IN GIT — see §11
```

Three repos exist on the owner's Desktop; only one is worked in. See
`docs/REPOS_AND_DEPLOY.md`.

- `Desktop/Sandy-App` → **this repo**, remote `AlsultanNabeel/sandy-backend`.
- `Desktop/Nabeel/Sandy` → read-only archive of the original single-owner project.
- `Desktop/sandy-web` → the website, a separate repo, deferred.

Deploy target: Heroku app `sandy-robot` (host `sandy-robot-3da0693d32f7.herokuapp.com`), database `sandy-app` (set by config var; the code default is `sany-db`). The
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
dyno and no job queue.** Long work — a chat turn with tools, image generation — runs
inside the request under a 120-second cap. If you add anything slower than that,
you are adding a queue first.

Every worker runs `bootstrap()`, so the periodic jobs used to start twice per
dyno. They are now behind `utils/process_leader.claim_leadership` — a `flock` on
the local filesystem, released by the kernel if the holder dies, so gunicorn's
replacement claims it on its own boot. The per-day nudge lock and the schedule
runner's compare-and-set claim stay: they are what makes this safe across
*dynos*, which a per-machine lock says nothing about. `mqtt_ingest` is deliberately
**not** elected — one subscriber for every board's heartbeat is a redundancy
decision, and `/api/diagnose` reports that listener per worker.

`wsgi.py` is production; `serve_api.py` is the local dev runner. Both build the
same app: `configure_logging()` → `bootstrap.init_runtime()` (Mongo, the stores'
indexes, MQTT ingest) → `create_app()` → `bootstrap()`. Nothing connects to
a database at *import* time — that is deliberate, and it is what lets the whole
package import in a test with no credentials. Do not add import-time side effects.

### 2.2 Directory roles

| Path | Role |
|---|---|
| `app/config.py` | The central env-var module. New code imports from here rather than calling `os.getenv` at a call site; older modules (`auth_handlers`, `ltm_crypto`, integrations/*, …) still read the environment directly. |
| `app/bootstrap.py` | `init_runtime()` (Mongo on `app.db`, the stores' indexes, MQTT ingest), then `bootstrap()`: `validate_config` (fatal → `RuntimeError`), Google creds, Sentry, `ensure_indexes`, and — on the elected worker — the nudge scheduler and the blocks' indexes + the schedule runner. Idempotent. |
| `app/db.py` | The single Mongo handle. Every store reads through `get_db()`. |
| `app/errors.py` | Typed error taxonomy. |
| `app/brain/` | The agent: the loop, its tools, short-term memory, held confirmations, persona, the fast path (§2.3–§2.5). |
| `app/blocks/` | The data layer — log / lists / schedules + the kinds table (§2.12). |
| `app/api/` | HTTP routes and the `/voice` WebSocket (§2.9). |
| `app/features/` | What is not a block: devices, nodes, scenes, focus, photos, users, usage, speaker id, firmware, device keys, research, weather, vision, account deletion. |
| `app/integrations/` | Clients for everything external: the chat client (`openai_client.chat_fn`), embeddings, Exa, Places, FLUX/Azure images, Gemini TTS, MQTT, the camera, Sentry. |
| `app/services/` | APNs, the `sandy_schedules` runner (once a minute) and the daily-nudge scheduler. |
| `app/utils/` | Tenancy (`tenant_db`, `tenant_version`), `ltm_crypto`, circuit breaker, background thread pool, process leader, profiles, time, Arabic days. Rate limiting lives in `features/usage_store.py` and `api/metering.py`. |

### 2.3 The agent — `app/brain/`

One model call with native tools, in a loop, on the blocks. Chat enters at
`loop.run_turn` (from `api/server.py::_run_authenticated_agent`, shared by
`/api/agent` and `/api/agent/stream`); voice enters at `voice.dispatch` (from
`api/voice_ws/tools.py::_dispatch_tool`). There is no other agent and no flag.

**The turn** (`loop.py`):

1. A held confirmation (`pending_state`, loaded by the route from
   `sandy_pending_state`) is resolved first: yes runs the held call, no cancels,
   a pick answers "which one", anything else drops the hold and is a normal turn.
2. **The fast path** (`fast_path.py`): a bare device command («شغّل الضو») is
   matched *whole* against the caller's own registered devices and run with no
   model call at all. It only picks the tool; `device_control`,
   `command_payload` and `tenant_owns_topic` run underneath it unchanged. Its four
   conditions, and why it is not the thing C8 bans, are in `CONVENTIONS.md` C8b.
   `SANDY_FAST_PATH=0` turns it off.
3. `context.build_system` (§2.5), then at most **6** model calls with native tools:
   model → tool calls → results (JSON tool messages) → model, until it answers in
   text. A tool asking for a yes or a choice ends the turn with a deterministic
   question and a held action, with no second model call.
4. Due `message_to_future_self` schedules (`future.py`) go into the system prompt
   and are marked `sent` only when the reply is not an error.
5. The turn is written to short-term memory (`stm.save`, with `via`).

**The model call** (`model.py`): the Azure chat deployment through
`openai_client.chat_fn()` — the process's one chat client, behind the `openai`
breaker and the param-quirk adapter — then OpenAI direct (`OPENAI_MODEL`), then
`None` and a fixed error sentence. Text streams through thread-local hooks
(`model.set_stream_hooks`), cumulative, which `/api/agent/stream` sets on the
thread that runs the turn.

`run_turn` returns `final_response`, `pending_state` (the route saves it for the
next turn) and `execution_result` (image bytes and caption when a tool made one).
The `[turn] …ms total — brain tools=[…]` log line says where a slow turn went.

### 2.4 Tools

Twelve (`tools.py`), voice adds `confirm`. Enums come from `kinds.KINDS`, so a new
kind needs no tool change.

| Tool | Does |
|---|---|
| `remember` | `entries.add(kind, text, data)`; `kind=mood` keeps a significant mood with the user's words sealed (`ltm_crypto`), once per turn |
| `recall` | entries + items + pending schedules, filtered by kind / list / since / until / query words (an alias like «مهامي» becomes the filter); compact rows |
| `list_add` | `items.add`; `due` parsed like `when`; a duplicate open item is reported, not added |
| `list_update` | by `id` or `match_text` (`matching.match_rows`: exact, contained, fuzzy ≥ 0.72): done / text / due / delete |
| `schedule` | `schedules.add`; `when` = ISO, else a bare weekday, else one model call (`when._parse_with_model`), else the deterministic Arabic date parser |
| `schedule_update` | move / rename / cancel (status `cancelled`) |
| `summarize` | the period's entries, items and schedules as rows; the model writes the summary, nothing is stored |
| `device_control` | a registered device by slug or label; `command_payload` validates, `send_to_topic` checks the topic is the caller's; an unknown device or action is refused with what is available |
| `scene_apply` | `scene_store.apply_scene` (actuates, schedules the reverts, §2.12) plus the room-node vocabulary fallback |
| `web_search` | `features/research.web_answer`: Exa snippets summarised in one model call, with sources |
| `weather` | `features/weather` |
| `image` | `vision.generate_image_with_azure` on the model's own prompt (FLUX, then Azure DALL-E) |

**A result says whether it happened** (`CONVENTIONS.md` C10): `ok`, `error`,
`reply`; `broke` when the tool raised (`tools.execute` catches it — one tool never
breaks the turn); `needs_confirmation` / `needs_choice` when it will not act yet.

**Confirmation** (`confirm.py`, `pending.py`): deletes, cancels and multi-row
changes return `needs_confirmation`; two matching rows return `needs_choice`. The
loop stores a `brain_confirm` pending (10 minutes, a nonce, `consumed_at`) and
asks «متأكد إنك بدك …؟ (اه/لأ)» or lists the candidates. `confirm.answer` is the
one yes/no resolver: letter-variant, digit and emoji folding, cancellation wins a
mixed reply, and a reply longer than four words is a new message, not an answer.
On voice there is no text turn to read, so the `confirm(answer)` tool passes the
user's words to the same resolver, and holds wait on the `voice` pending thread.

**On the voice path everything that did not happen is marked**
(`voice._tagged`), because an unmarked refusal is exactly what Gemini reads as
success and confirms to the user: `[فشل التنفيذ]` for breakage, `[لم يُنفَّذ]`
for a refusal. A held action is "not done yet", neither.

### 2.5 Memory

| Layer | Module | Store |
|---|---|---|
| Short-term conversation | `brain/stm.py` | `sandy_stm`, one doc per thread (`<thread>:<user>`), up to 40 messages, TTL 30 days; the model sees the last 24 (`context.RECENT_TURNS`, chat and the call alike) |
| What she knows | `brain/context.py` | `fact` entries (the newest 30 distinct ones of two words or more; anything still ciphertext is left out) and the onboarding profile (`sandy_users.onboarding`: name, interests, notes, daily-question answers) |
| What is open now | `brain/context.py::state_block` | open items per list and pending reminders, with their ids and times in the user's zone, so a vague mention is resolved by the model and edited by id (messages to future self stay out) |
| Related past | `brain/context.py::similar_entries` | nothing for a message under three words; else the 8 nearest entries that are not facts, chat summaries or habit ticks, from the Atlas vector index `entries_vector` (tenant in its filter); text search when there is no vector or no hit |
| Conversation summaries | `brain/stm.py::_summarize` | one `summary` entry (`data.thread_id`) per conversation, in the background: when a message comes after a 30-minute pause, or when a thread passes 40 messages and drops to its newest 20; turns are marked `summarized` so none is summarised twice; `recall` leaves them out unless asked |
| Held actions | `brain/pending.py` | `sandy_pending_state`, keyed `<chat_id>:<thread_id>`, TTL 1 hour |

**One memory across every channel.** App chat (`/api/agent`), the robot's voice
(`/voice`, HMAC hello → the paired node's `user_id`) and in-app live voice
(`GeminiLiveManager` → the same `/voice` socket with a JWT hello) all resolve to
the same `user_id`, read the same `sandy_stm` recent turns
(`stm.recent_turns_for_user`: a person's last turns across their five newest
threads, ordered by their own timestamps) and the same profile and facts, and
write their turns back with `via`. Threads stay separate: a chat sees the other
channels' last turns before its own, without repeating a line (`stm.history`).
`tests/test_memory_is_one_memory.py` holds this.

**The voice instruction is cached per tenant version** (`voice_ws/tools.py`, per
process and in `sandy_prompt_cache` across workers), because building it used to
take seconds with the microphone running. It holds the persona, the profile and
the facts — never the recent turns, which are added per session
(`with_recent_turns`). `utils/tenant_version.VERSIONED` names the collections it
is built from (`sandy_users`, `sandy_entries`): a write there through `scoped()`
bumps the version, and `prompt_prewarm` rebuilds it in the background for tenants
who use voice. Bump `_PROMPT_REV` when the cached text changes shape.

**One embedding per call site, none without a key** (`integrations/embeddings.py`,
built once, eight-second deadline). Entries are embedded when written, except
sealed moods.

Short-term memory is on Mongo, not Redis, on purpose: the free Redis tier hit its
monthly request cap and memory silently froze. Mongo has no per-request quota and
was already wired. Don't "fix" this back to Redis without solving the quota.

**Context does not cross a thread boundary.** The active tenant lives in a
`ContextVar`, and a pool worker starts with none — so a `scoped()` store called
on a pool thread reads nothing, writes nothing, and returns an ordinary empty
result. `utils/thread_pool.submit_background` runs every job in a copy of the
caller's context; the voice path passes the identity explicitly to everything it
runs in an executor and enters `active_user_profile_context` there. **Never add a
bare `.submit()` on a path that touches a scoped store.**

### 2.5b Whose name she says

Eight strings that reach a customer had the owner's name typed into them, and
the worst was the live voice prompt: *"you are in a voice conversation with نبيل
(your partner)"* — the first thing every robot in the world is told about the
person standing in front of it.

`user_profiles.speaker_label()` is the one answer, reading the name from
first-run setup. `HAS_NO_NAME` (`المستخدم`) is the fallback, and a caller
building a *discriminating* sentence — "this is not X", "even if he claims to be
X" — must **branch** on it rather than substitute it: «مش المستخدم» denies that
the speaker is the user, which is not a sentence. **The speaker gate is handed the
identity, never left to find it.** `_verify_owner` runs on a pool thread where the
session context does not reach — that is why it takes a `user_id`. An empty id
means `has_profile("")` is false, which takes the "no voiceprint enrolled, allow"
branch: a comparison that never ran returning *owner*.

**Both halves of the voice prompt build such a sentence** — the standing
instruction in `voice_ws/tools.py` and the per-turn note in `voice_ws/speaker.py`
— and they must agree, or the model is left deciding whether «المستخدم» and
«صاحب الحساب» are the same person before it decides whether to hand over
somebody's memories.

The voice path resolves the name once per session into a context variable
(`voice_speaker_label`), because `_speaker_directive` is awaited on the loop
relaying audio and a `find_one` there is an audible pause at the end of every
sentence. `_live_session` resolves it before the instruction build, not inside
it: `run_in_executor` does not copy context back.

`config.py` is deliberately untouched. *"طوّرك نبيل السلطان"* is a developer
credit and belongs to every customer.

**Gender and language are told to the model, not assumed.**
`address_instruction()` keeps its escape hatch — masculine by default because
Arabic forces a choice, switching to feminine the moment the speaker turns out
to be a woman. `brain/persona.LANGUAGE_RULE` is appended by code beside the
anti-injection and no-promises rules, so it survives a custom persona: reply in
the language of the last message, per message. It also **says** it outranks the
dialect preset beside it — «احكي باللهجة الفلسطينية» is more specific and about the
same decision, and without that clause an English-only customer gets two orders
and the narrower one wins.

A device is actuated only through `device_store.tenant_owns_topic`, which asks
whether the topic belongs to a device in the *calling tenant's* registry (§2.7);
there is no owner-only gate.

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
request sets a tenant. Indexes lead with the tenant field (`user_id`, or `chat_id` on the older collections).

Three request-path collections are keyed by hand, each on the caller's id on every
call: `sandy_stm` (`<thread>:<user>` plus a `user_id` field), `sandy_pending_state`
(`_id` `<chat_id>:<thread>` and a `chat_id` filter) and `conversations`
(`user_id`). The infrastructure stores that key on something other than a tenant
(users, nodes, voiceprints, push tokens, usage, photos' GridFS) are listed with a
reason in `tests/test_tenant_scoping_guard.py`.

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
- **`room_device.send()`** takes a device *name* and resolves the
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

- Control types: `switch`, `dimmer`, `enum`, `media`, `cover`, `ir`, `text` (free text for her screen, limited by `meta.max_bytes`, default 255).
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

Runs at two points. Label and room are never overwritten, so an owner who renames
her robot's neck keeps the name; `control_type` and the catalogue's `meta` *are*
refreshed on existing rows (`_refresh_from_catalogue`), because they describe the
hardware:

- `pair_node()` — only when a code already paired is paired again (a first pairing
  stores no outputs; the next heartbeat provisions).
- `ingest_status()` — so a firmware upgrade that adds a part appears on its own.

The heartbeat path has no tenant (it is the MQTT thread), so it enters the owner's
context using the owner id already on the node document from when that tenant
paired the code. **A heartbeat cannot nominate its own owner.**

### 2.9 HTTP surface

88 HTTP route handlers on 71 paths, plus two WebSockets (`/voice`, `/voice/enroll`).
All under `/api/*` except `/health`, `/`, `/webhook/revenuecat` and the sockets.
Registered by explicit `register_*_api(app, …)` calls in `api/server.py` — there
are no Flask blueprints, so **route discovery means reading `server.py`'s
registration block**, not grepping for blueprints. `tests/test_routes_kept.py`
pins every route a client calls, with its methods.

Who calls what:

- **The iPhone app** — auth (`/api/auth/apple|google|email/login|email/register`),
  account (get / reset / delete), chat (`/api/agent`, `/api/agent/stream`),
  conversations (list, create, get, rename, delete, messages, search), the blocks
  (below), `/api/summary`, `/api/kinds`, daily nudge (+ answer), devices and nodes
  (control, IR learn, pairing, snapshots, Wi-Fi), `/api/life/focus` (+ start /
  stop / history), `/api/life/scenes` (+ actions / apply / delete), photos
  (+ albums, file), images (`/api/image`, `/api/image/edit`, `/api/analyze-image`),
  `/api/research`, `/api/weather`, `/api/persona`, `/api/onboarding`,
  `/api/features`, `/api/subscription`, push register / unregister,
  `/api/voice/tts`, and the `/voice` socket for live calls. The share extension
  uses `/api/agent`, `/api/analyze-image`, `/api/photos`, `/api/entries` and
  `/api/items`.
- **The boards** — `/voice` (the brain), `/api/cam/upload` (the camera),
  `/api/firmware/manifest` and `/api/firmware/image/<version>` (OTA).
- **The owner's tooling** — `/api/firmware/publish` and `/rollout`
  (`scripts/publish_firmware.py`), `/api/diagnose` and `/health` (by hand).
- **RevenueCat** — `/webhook/revenuecat`.
- `/voice/enroll` records a voiceprint for speaker verification (§3.2); no
  shipped client opens it yet, and it is the only way to enrol one.

**The blocks** (`api/blocks_api.py`, §2.12) — every route `require_tenant` except
`/api/kinds` (`require_auth`), so the block stores' scoped handles do the
isolation; a bad input is 400 `{"error": <code>, "message": <Arabic>}`, text
capped at 2000 characters and `data`/`payload` at 8000 of JSON:

| Route | Does |
|---|---|
| `GET/POST /api/entries`, `PATCH/DELETE /api/entries/<id>` | the log; `GET` filters `kind`, `since`, `until`, `q`, `limit` |
| `GET/POST /api/items`, `PATCH/DELETE /api/items/<id>` | the lists; `GET` filters `list`, `done`, `q`, `limit`; `PATCH {"due": null}` clears it |
| `GET/POST /api/schedules`, `PATCH/DELETE /api/schedules/<id>` | anything that fires; `GET` filters `kind`, `from`, `to`, `status`, `limit`; `fire_at` must be future; `recurrence` is daily/weekly/monthly/yearly or an RRULE; the app may set status only to `pending`/`cancelled` |
| `GET /api/kinds` | `kinds.KINDS` as `{name, block, labels:{ar,en}, icon, prefix, fields:{name: type}}` — the app builds its screens from it |
| `GET /api/stats` | My Life's numbers over the whole log in the user's zone: entries per day for 30 days, and this month's spending (in all and `by_category`), habit check-ins and entries (summaries left out), plus the monthly `budget`; the app adds what it made since |
| `POST /api/budget` | `{amount}`: the monthly spending limit on `sandy_users.budget` (0 removes it); the app rings at 80% and 100%, and `remember` of an expense tells the model past 80% |
| (expense category) | an expense saved with no `data.category` (app sheet on "automatic", or Sandy leaving it out) gets one from its words in the background (`brain/categorize.py`, one short model call; "other" when no model) |
| `POST /api/summary` | `{period, focus?}` → `{text, count}`: the brain's `summarize` rows, one model call (`brain/summary.py`); metered; nothing recorded → a fixed sentence, no call |

Datetimes go out as ISO in the user's zone and come in as ISO (naive = user's
zone; a bare date in `until`/`to` covers its day). A row with `encrypted` in its
`data`/`payload` is decrypted for its owner and re-sealed on edit; a
`message_to_future_self` is sealed at rest.

**Every route that spends money on a provider is metered** through
`api/metering.py` — the chat routes, image generation and analysis, web and
place search, photo tagging and `/api/summary`, one unit each against the
caller's tier. A new paid route calls `meter_claims`.

**No route issues a guest token.** `make_token` still honours a `guest` role;
chat and images refuse one with 403, `require_tenant` routes refuse it, and the
rest resolve it to an empty tenant.

### 2.10 Auth

`api/auth_handlers.py`. JWT, HS256. Owner tokens 7 days, guest 48 hours. Login
rate-limited to 5 attempts per 15 minutes per IP, with an in-process sliding
window as a fail-closed fallback when Mongo is down. `JWT_SECRET` has no default —
an empty secret would let anyone forge a token, so it refuses rather than degrade.

### 2.11 External services

The chat model is `openai_client.chat_fn()`: Azure OpenAI (`AZURE_OPENAI_CHAT_DEPLOYMENT`)
when the Azure trio is set, else OpenAI direct; the brain falls back to OpenAI
direct (`OPENAI_MODEL`) when the primary call fails. Every other model call —
the conversation title, the STM summary, the daily agenda line, image analysis
and photo tagging, the web-search summary, the time parser — uses the same client.
Speech-to-text on the voice path is Gemini Live's own input transcription. TTS
(`/api/voice/tts`) is Gemini only. Images are Azure FLUX with an Azure OpenAI image
fallback. Embeddings are Azure (`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`) or OpenAI
direct. Research is Exa; places are Google Places. Push is APNs over HTTP/2 (`h2`
is in `requirements.txt` for exactly this). MQTT is HiveMQ Cloud over TLS.

Circuit breakers (`utils/circuit_breaker.py`) wrap `openai_client`, `exa_client`,
`gemini_tts` and `features/weather`. Not wrapped: `azure_flux`, `azure_image`,
`google_places`, `services/apns`, `embeddings`.

**None of the breakers pass `timeout=`, and that is on purpose.** The class
supports one and it looks like the missing half; it is not. `_invoke` enforces a
deadline by submitting to a shared eight-worker pool and waiting on the future,
so *queue* time counts against the call's own budget and the resulting timeout is
scored as a failure. Switch it on across every client and load alone can open a
breaker in front of a provider that is answering perfectly — and `future.cancel()`
cannot stop a running job, so slow calls keep their slots exactly when the queue
is longest. Per-request deadlines belong on the SDK call, where they cost no
threads: `OPENAI_CHAT_TIMEOUT_S` and `embeddings.EMBED_TIMEOUT_S` are there for
that reason.

A missing key disables only its own feature — the app still boots.

**Parameter quirks are learned once per deployment.**
`openai_client._create_chat_adapting` retries a call without a parameter the model
refused (`reasoning_effort`, `temperature`) or with `max_tokens` renamed, and
`_ADAPTED` remembers the answer per model name for the life of the process, so a
refused parameter costs one round trip, not one per message.

**Where a chat turn's time goes** is one log line: `[turn] …ms total — brain
tools=[…]`, from `brain/loop.py` (`(fast)` when the fast path answered). Grep it
before theorising.

### 2.12 `app/blocks/` — the data layer

Every user feature is a row in one of three collections, reached through
`scoped()` (§2.6) on `user_id`: no tenant → empty result, nothing written.
`init_blocks(db)` creates the indexes on the raw handle (tenant-first).

| Module | Collection | Holds |
|---|---|---|
| `blocks/entries.py` | `sandy_entries` | LOG — what happened or what Sandy learned: `{kind, text, data, at, source, embedding, migrated_from}` |
| `blocks/items.py` | `sandy_items` | LISTS — anything ticked off: `{list, text, done, due, priority, data, created_at, done_at, migrated_from}` |
| `blocks/schedules.py` | `sandy_schedules` | SCHEDULES — anything that fires: `{kind, text, fire_at, recurrence (RRULE), payload, status, migrated_from}` |
| `blocks/kinds.py` | — | The kinds table: every log kind, list and schedule kind with labels, SF Symbol, the words a user says for it (`aliases`) and typed `data` fields. `validate()` refuses an unknown kind or an undeclared/mistyped field. A `project:` row matches any `project:<name>` list. |

Each module is add / get / update / delete / list with filters (kind or list,
date range, done/status, text). `entries.embed_text` is the one door to an
embedding (`integrations/embeddings.py`), so no key → `null`.

**Adding a feature is adding a row to `kinds.KINDS`.** The brain's tool enums, the
REST validation and the app's screens (`/api/kinds`) all follow it.

`scripts/migrate_to_blocks.py` copied the old stores in: dry run by default
(counts per source and per target, three sample docs per source), `--apply` to
write, `--user <id>` for one tenant. Every written doc has `migrated_from:
{collection, id}` and an `_id` derived from it, so a re-run skips what is
already there. It only reads the old collections, which are left in place until
the owner drops them (§8). The mapping table is in its `SOURCES`; its docstring
lists what is deliberately not migrated.

**The schedule runner** (`services/schedule_runner.py`) is the one job that fires
anything, on the leader-elected scheduler (§2.1), once a minute. A due row
(`status` pending, `fire_at` ≤ now) is claimed by a compare-and-set on its own
`(status, fire_at)`: a one-off moves to `sent`, a recurring one to its next RRULE
time (anchored in local time, so "every day at 8" survives DST), and only the
worker whose update matched fires it, so nothing fires twice across workers or
dynos. `fired_at` and `last_error` are set on the row.

| Kind | Firing |
|---|---|
| `reminder` | The phone rings it locally from `GET /api/schedules`. The server also pushes over APNs when `services/apns.py` is configured, unless the row is more than 15 minutes late. `failed` only when devices exist and none took the push. |
| `scene` | A scene's timed revert: `scene_store.apply_scene` cancels the tenant's pending `scene` rows and writes one per `for_min` action; the runner sends it through `scene_store._actuate`, and a miss retries a minute later up to `MAX_TIMER_TRIES`, then `failed`. |
| `daily_nudge`, `summary_nudge` | push text only; `failed` when no device took it (no APNs, no token, every send refused). |
| `message_to_future_self` | not fired here: the next chat reply delivers it (§2.3). |

A recurring row that fails stays armed for its next time with `last_error`. A
migrated row more than 15 minutes late is settled without firing: its old store
already fired it, and the migrated scene timers in particular were never marked,
so replaying them would switch lights hours later.

The daily nudge push itself still runs on its own scheduler
(`services/nudge_scheduler.py`, 08:00 local, one worker per day by a Mongo lock);
`/api/daily-nudge` builds the day's nudge from the blocks (open tasks, overdue,
pending reminders) and the last STM turn ("was up late").

### 2.13 `app/brain/`, file by file

| Module | Holds |
|---|---|
| `loop.py` | `run_turn`: held action → fast path → context → model/tool loop → future-self delivery → STM save |
| `model.py` | the model call (Azure via `chat_fn`, then OpenAI direct), streaming, the stream hooks |
| `tools.py` | the tool table (JSON schemas from `kinds.KINDS`), `declarations()` for Gemini Live, `execute()` |
| `tools_blocks.py` | `remember`, `recall`, `summarize`, `list_add`, `list_update`, `schedule`, `schedule_update` |
| `tools_world.py` | `device_control`, `scene_apply`, `web_search`, `weather`, `image` |
| `context.py` | the system prompt, steady parts first so the provider can cache the prefix: persona, rules, the channel line (chat: written, emoji welcome; voice: heard, no emoji), profile, facts, open state, related entries, the clock, and last the reply language (this message's, Arabic or English, decided in code) |
| `persona.py` | `build_effective_persona`: tone (custom instructions or `SANDY_PERSONALITY`), dialect preset, then the language, no-promises and anti-injection rules, then `SANDY_IDENTITY_LOCK` last |
| `stm.py` | short-term memory and the cross-channel read |
| `confirm.py`, `pending.py` | held actions: the question, the yes/no resolver, the pick-by-number, the lifecycle and the store |
| `voice.py` | the voice session's tools: `declarations()` (+ `confirm`), `dispatch()`, the C10 marks |
| `fast_path.py` | the model-free device command (C8b) |
| `matching.py` | the row-name normaliser and the exact → contained → fuzzy ladder |
| `when.py` | `when` / `due` / `since` / `until` / `period` parsing |
| `future.py` | due messages to your future self |
| `summary.py` | `/api/summary`: the `summarize` rows written up in one call |
| `ctx.py` | `TurnCtx` — what a tool knows about its turn |

The speaker gate (`SANDY_REQUIRE_SPEAKER_AUTH`, §3.2) guards the brain's
destructive voice calls (`speaker._is_sensitive_call`).

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
      ├─ VAD                  measured (adaptive) RMS floor + silence + minimum utterance
      ├─ tools.py             the instruction (persona, profile, facts, recent turns)
      │                       and the brain's tools (brain/voice.py), same as chat
      └─ memory.py            writes the turn into short-term memory (brain/stm.py)
  → Gemini Live
  → audio back → speaker + amplitude-driven lip-sync
```

### 3.1 The handshake contract

Firmware sends, on connect:

```json
{"type":"hello","device_id":"<id>","ts":<unix_ms>,"hmac":"<hex>"[,"kv":2]}
hmac = HMAC-SHA256(key, device_id + str(ts))   # key = the board's own key when kv=2, else SANDY_WS_HMAC_KEY
```

Server replies `{"type":"auth_ok"}` (to a device it may add `broker` MQTT credentials
and, in the pairing window, a `device_key`) or `{"type":"error","msg":"<code>"}`. Error codes and what each
actually means:

| Frame | Meaning |
|---|---|
| `auth_ok` | accepted, start streaming |
| `auth_fail` | the HMAC did not match, a board with its own confirmed key signed with the shared one, or the JWT is not a signed-in account |
| `replay` | `ts` was outside ±30 s — the **board's clock** is wrong, not the key |
| `bad_handshake` | malformed hello |
| `auth_not_configured` | the server has no `SANDY_WS_HMAC_KEY` at all |
| `key_unknown` | signed with `kv` 2, but the server holds no key for that board (unpaired or revoked); the board drops its key and falls back to the shared one |

The `ts` must be wall-clock, so the firmware blocks on SNTP before it can connect.
A board that cannot reach a time server will sit there forever while the wake word
keeps working — that failure looks exactly like a dead network.

Three ways in, checked in this order: a legacy plain-text secret (dev/echo tests),
a browser JWT (`{"type":"hello","token":…}`, any signed-in account; guests are
refused), then the device HMAC. With no key configured at all it refuses unless
`SANDY_WS_ALLOW_OPEN=1`, so a missing env var in production cannot leave the
socket open.

You can probe all of this from a browser without hardware — see §10.

### 3.2 Speaker verification

`features/speaker_id.py` + `voice_ws/speaker.py`. CAM++ via sherpa-onnx, running
locally: no account, no torch. Gated by `SANDY_REQUIRE_SPEAKER_AUTH=1`, off by
default, and it only guards the sensitive calls (`speaker._is_sensitive_call`):
`list_update` delete / `all_matching`, `schedule_update` cancel / `all_matching`,
`schedule` of a `message_to_future_self`, and `confirm` (which only runs a held
delete or bulk change). With no voiceprint enrolled it allows — it does not lock
the owner out before enrolment. Voiceprints are recorded over `/voice/enroll`.

---

## 4. The firmware — robot brain

`firmware/brain-core/`, ESP-IDF, ESP32-S3. `sandy_voice.c` is about 2000 lines and is
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
| `sandy_audio_ctl.c` | mic gain/mute, volume, noise suppression; persisted in NVS |
| `sandy_screen.c` | owner text/picture on the display, Arabic fonts 24/32 |
| `sandy_ir.c` | IR learn + replay (§4.5) |
| `sandy_provision.c` | first-run SoftAP setup (§4.5) |

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
`LINK_STALL`, `AUTH_FAILED`, `LOW_MEMORY`.

Rules:
- **Subsystems must not set the face directly for error conditions.** Call
  `status_set()`. Direct face writes are how a half-finished state stayed on screen.
- `status_set()` is idempotent — re-reporting the same condition does not
  re-announce, so retry loops don't make her repeat herself.
- The banner is still Latin (Montserrat 14), but Arabic fonts are in the build
  (DejaVu 16 with shaping, `fonts/sandy_font_ar_24.c` / `_32.c`, used by
  `sandy_screen.c`). An Arabic banner now only needs a font set on `s_banner`.
- Voice clips are **not** flashed yet — the partition table has no room reserved.
  The sentences are in the table; the hook that would speak them
  (`voice_say_status()`) is not written yet.

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
for more than 3 s raises `SANDY_ST_NET_SLOW` when RSSI is below −75 dBm, otherwise
`SANDY_ST_LINK_STALL`. Anything queued past 32 KB (~1 s) is dropped oldest-first so
she answers the present, and an uplink squelch sends only audio above a measured
room floor. The buffer is reset on session close so the tail of
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
sandy/node/<node_id>/mood · servo · gesture · buzzer · base · led · autonomous · focus · ota
                     · wifi · factory_reset · screen · screen_size · screen_img
sandy/node/<node_id>/mic_l · mic_r                 mute (payload "on" = unmuted)
sandy/node/<node_id>/mic_l_gain · mic_r_gain       digital gain, 0..300
sandy/node/<node_id>/volume · speaker_test · noise
sandy/node/<node_id>/status                        heartbeat → ingest_status
sandy/node/<node_id>/ir/learned                    captured IR code
sandy/node/<node_id>/cam/request · command · wifi · flash · flash_level · flash_mode · stream · framesize (in)
sandy/node/<node_id>/cam/snapshot · status · event (out)
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

#### Infrared

`main/sandy_ir.c`, added 23 Aug 2026, flag `ENABLE_IR`, RMT on `PIN_IR_TX` (21,
through a transistor) and `PIN_IR_RX` (38). The backend half — the `ir/learned`
topic, `/api/nodes/<id>/ir/learn`, the `ir` control type with `meta.buttons` —
had been complete for a while with nothing on a board to answer it.

One output, `ir`, two payloads: `learn` arms the receiver and the next press is
published to `sandy/node/<id>/ir/learned`; anything else is a recorded code to
replay. That is the backend's existing shape, not a new one — a button on an
`ir` device already carries its code as the payload, so the board keeps no state
and a second robot learns nothing it was not taught.

**Raw capture, not protocol decoding.** The pulse train is recorded and replayed
verbatim as microsecond durations, marks at the even indices. Decoding is the
smaller-sounding job and the one that fails on the customer's air conditioner.
The mark/space ordering is the whole format: invert it and the replay looks
perfect on a scope and does nothing in the room.

**The `ir` catalogue row carries no `meta`, deliberately.**
`node_provision._refresh_from_catalogue` merges the catalogue's meta over the
device's on every heartbeat, so a `"buttons": {}` row — even empty — would erase
every button the owner taught, every five seconds, for ever. An absent meta is
how a field is declared to belong to the owner.

"Turn, then fire" needs no new contract: it is a scene — neck angle, then the IR
button.

#### First-run network setup

`main/sandy_provision.c`, added 23 Aug 2026, flag `ENABLE_PROVISION`. When no
network answers within `PROVISION_WINDOW_MS` (90 s), the board raises its own
access point — `Sandy-<pair code>`, WPA2, password `sandy<pair code>` — serves a
scan-and-pick page on `192.168.4.1`, and prints the network name on its own
screen. The chosen credentials go through `wifi_sandy_switch`, which proves them
before saving and reverts on failure, so a typo cannot leave a board booting onto
a network that does not exist.

Three things here are load-bearing and easy to undo by accident:

- **APSTA, not AP.** The station side has to stay up to scan and to test. In
  plain AP mode the scan returns nothing and every choice fails invisibly.
- **The page answers before the radio moves.** `wifi_sandy_switch` tears down the
  association the page is served over, so a reply written after it returns never
  reaches the phone and the browser reports failure for a setup that worked.
- **`_retry_task` yields** while `s_switching` or `provision_is_active()`. A blind
  `esp_wifi_connect()` inside a scan or a credential test makes both fail, and it
  reads as a wrong password.

The window is long on purpose: a robot that enters setup whenever the router is
slow is worse than one that never does. It doubles as the recovery path when an
owner changes routers — previously the board retried a dead network for ever.

Pairing is still separate: this hands over the network, the code is still typed
in the app.

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

Updated 23 Aug 2026. **This table is the answer**, and the only other place that
describes the hardware is `firmware/brain-core/HARDWARE.md` — generated by
`scripts/gen_hardware_doc.py` from the firmware itself, with
`tests/test_device_system.py` failing the suite when it drifts. (`docs/HARDWARE_CAPABILITIES.md`
was named here twice and does not exist; the generator has never written it.)

| Part | Reachable from the backend | Physically working |
|---|---|---|
| Camera (ESP32-CAM) | Yes — flash, snapshot, stream, framesize, quality | Yes — `firmware/vision-core/`, flashed and on the broker |
| Face / display | Yes — all 25 moods | Yes |
| Microphones | Yes — per-channel gain, mute, live level | Yes |
| Speaker | Yes — volume 0..100, test tone | Yes, through the voice path |
| Noise suppression | Yes — off / mild / medium / aggressive | Yes |
| On-board LED | Yes — off / idle / listening / talking, plus 11 effects | Yes |
| Neck servo | Yes | **Not physically wired yet** |
| Base motors | Topic exists | `ENABLE_MOTORS = 0` |
| Buzzer | Yes — 17 melodies | Yes — passive piezo on GPIO 17 |
| Distance sensor | No | Dropped; `ENABLE_SENSOR = 0` |
| Room light (room node) | Yes — `room/light`, provisioned from its heartbeat | Yes — servo presses the wall switch |
| Room music (room node) | Yes — `room/music`, stop/pause/resume/next/prev | Yes — DFPlayer over UART2 |

"Mute the left mic, speak, and watch only the right meter move" now works end to
end — that is the point of per-channel metering, and it is how you tell a dead mic
from a cross-wired one without a multimeter.

**Everything in the first column is true of the source, not of the board on the
desk, until it is flashed.**

The camera board program is no longer missing — `firmware/vision-core/` exists, is
flashed, and answers on the broker. Neither is the IR code (`main/sandy_ir.c`, on the brain; §4.5), though
it is written and not yet tried on hardware. Still genuinely missing: two-mic
beamforming.

The Arabic display font is done: `main/fonts/` now carries the typeface at
twenty-four and thirty-two pixels alongside LVGL's built-in sixteen, which is
what makes the text-size control real rather than decorative.

---

## 5. The other boards

- **`firmware/vision-core/`** (ESP32-CAM) — the camera board's own program. It exists,
  it is flashed, and it answers on the broker (§4.6). This section used to say
  in bold that it did not exist, while §4.6 two pages later said it was working
  — the map contradicting itself, which is worse than either answer.

  What it has to do is set by what the backend already expects.
  `app/integrations/camera_client.py` publishes the request, holds the pieces
  and hands back one JPEG; the sketch derives its `node_id` from
  `SANDY_PAIR_CODE` in its own `secrets.h`, which must be **flashed with the
  same code as its robot's brain** — that is what makes the two boards one node
  instead of two things to pair. Topics are built once in `setupMQTT()` before
  any subscribe, because empty topics leave the board publishing into
  `sandy/node//cam/...` and looking healthy while nobody hears it.

  For the record, because it cost a long time: every fix aimed at the camera
  before that sketch existed was aimed at plumbing that was already correct. The
  snapshot request was published exactly right and nothing was subscribed; no
  `cam/status` heartbeat was ever sent, so the address the live view needs never
  arrived, and "couldn't get the address" was the literal truth.
- **`firmware/room-node/`** (classic ESP32) — the room node: light servo and DFPlayer, under
  `sandy/node/<id>/room/`.

---

## 6. iPhone app

`ios/SandyApp/`, SwiftUI, ~17 400 lines, 14 feature folders. Swift is one module,
so folders are organisation only.

- `App/` — `SandyApp`, `AppState` (holds the base URL), `MainTabView`. **Three tabs**:
  Today, Sandy (the orb in the middle of the tab bar: tap = chat, hold = live call) and
  My Life. Profile opens from the avatar on Today and holds memory (the `fact` log),
  robot, photos, weather settings, persona and account.
- `Features/Today/` — one screen: a sentence about the day, the ask bar (`AskBar`: one
  field for everything, sent to `/api/agent/stream`; Sandy decides what it is and the
  day refreshes; the quick-add shortcut focuses it), the rest of the day as a timeline
  with a live "now" mark (`DayRibbon`), untimed tasks, habits as rings, today's spending,
  focus and home controls. The weather is a read-only corner, like the lock-screen clock.
- `Core/Networking/` — `APIClient` split into 9 extensions by domain, behind
  `APIClientProtocol`. **Add new endpoints as an extension, not to the base class.**
- `Core/Auth/` — Keychain (`…ThisDeviceOnly`), Google sign-in, auth view.
- `Core/Intents/` — App Intents / Siri shortcuts, including device intents.
- `Core/Stores/LoadableStore.swift` — the shared load/error/empty state machine.
- `Features/Blocks/` — **the screens for the blocks (§2.12)**: one generic list screen
  (`ItemsView`, any list in the kinds table; a habit keeps `data.days` (1 = Sunday … 7) and
  `data.time` and shows on Today only on its days, its streak skipping the others; a task
  with `data.repeat` (daily | weekly | monthly) is never closed — `items.update` moves its
  `due` on instead; habits check in per day as `habit` log
  entries instead of being "done"), one schedules screen (`SchedulesView`, reminders and
  messages to future self) and the log (`LogView`, the My Life tab, with the on-demand
  summary, search, a thirty-day activity strip and a card per list on top).
  `KindsStore` loads `/api/kinds` once; My Life builds a card per list from it, so a new
  list needs no app change. **Offline first:** every block change is applied on the
  phone, saved to `DiskCache` and reaches every copy of the same rows (the stores on
  screen, else the file on disk), then goes through `Core/Cache/Outbox.swift`, a
  per-account queue on disk sent in order now, on reconnect, or on return to the front.
  New rows carry their own 32-hex `id` (the blocks POSTs accept it and a resent POST
  returns the row already there). While the outbox holds anything, a reload keeps the
  phone's copy instead of the server's. Only a server refusal undoes a change.
  Done ticks and deletes (lists, reminders, log, conversations) go through
  `Core/Stores/UndoCenter.swift`: one «تراجع» offer at a time; a delete leaves the
  screen at once and reaches the server only when the offer ends (4 s, the next offer,
  or the app leaving the front). `DesignSystem/PermissionCard.swift` shows a denied mic
  or notifications where they are needed (ask bar mic, the call, reminders, Profile).
  `DesignSystem/DisplaySettings.swift` holds Profile › Display (text step, element scale,
  light / dark / automatic) and `scaledFont`; every colour token has a light and a dark
  value. `DesignSystem/Accessibility.swift` gives list rows one screen-reader element with
  their gestures as named actions, and `Announce` speaks replies, errors and undo offers;
  every animation goes through `.reduced` (none under Reduce Motion).
  Chat: long-press copy / share / select on any message, «write it again» on Sandy's last
  reply and «edit and resend» on the user's last line (both through
  `POST /api/conversations/<cid>/rewind`, which also takes back what that reply did to
  the blocks: every block write in a turn is journaled with its before-state
  (`blocks/_base.journal`, kept on the reply's STM turn as `effects`) and `_base.undo`
  reverses it; device actions are not undone), a stop button that keeps what arrived
  (`POST …/stop`: a running turn stops before its next tool via `brain/stops.py`, and
  memory keeps only the shown part with a «cut here» note), and a failed line marked
  with «أعد المحاولة».
  Attachments (`Features/Sandy/ChatAttachments.swift`): photos, the camera and documents
  upload at once to `POST /api/attachments` (`features/attachments.py`, `sandy_attachments`,
  bytes inline; images 8 MB, documents 5 MB; PDF / Word / text read to at most 20 000
  characters), wait above the field with their progress, and go with the message as ids:
  the turn gives the model the photos as images and the documents as text, memory keeps
  «[صورة: name]». An image Sandy draws is saved the same way and comes back as `image` on
  the reply; the history keeps `attachments` on each message.
  Loading (`DesignSystem/Loading.swift`): skeleton rows with a shine on first loads,
  `LoadingDots` inside buttons, and `SandyWaiting` (her face and changing lines with the
  user's name) for long waits; nothing moves under Reduce Motion.
  Profile is in four groups (account, app, Sandy and your data, help). Notifications
  (`Features/Profile/SettingsViews.swift`): a switch per kind (reminders, the daily
  nudge, Sandy's proactive nudges) and quiet hours, kept on the phone (`NotificationPrefs`,
  applied by NotificationManager: a kind off is not scheduled, a time inside the quiet
  hours rings silently) and on the server (`GET/POST /api/notification-settings`,
  `features/notify_prefs.py`: the schedule runner and the daily send skip a kind turned
  off and push silently in the quiet hours). Support sends `POST /api/feedback` with the
  version and device (`sandy_feedback`). The privacy, terms and support-mail values live
  only in `App/AppLinks.swift`, empty until the release.
  Today has a large home-control button, a robot button beside it when a board that
  speaks («audio» capability) is linked, and «أو قولي لساندي شو بدك» under them.
  `Services/Guidance.swift`: one-time TipKit tips (the orb's hold-to-call, row actions,
  the month strip, message actions; at most one a day, gone for good on «فهمت») and
  `ReviewPrompter` (asks for a rating after every fifth finished task, or after a week
  with ten replies; never within ten minutes of an error; at most every 120 days).
  The robot screen (`Features/Sandy/RobotView.swift`) holds everything about her: her
  state now and quick buttons, her body (`RobotControlView`: face, movement, screen,
  light, sound, camera), the parts test, her board's Wi-Fi, «why isn't a part showing?»
  (`DiagnoseView`, `GET /api/diagnose` in plain words) and linking/unlinking. Room
  scenes (`RoomScenesSection`) are in home control. Project lists Sandy made from chat
  («project:<name>») get a card each in My Life.
  Habits: a committed day is one on which every habit due that day was kept; the
  commitment days and the streak (days with nothing due neither count nor break it)
  come from `blocks/habits.py` (up to yesterday, `/api/stats` → `habit_progress`, and
  in Sandy's state block), and the phone adds today when its last habit is ticked.
  Shopping: when the user says he bought something on the shopping list (any wording),
  the rules tell the model to tick it by id with list_update (or set `qty` to what is
  left), log an expense if a price was said, and never add what is not on the list.
  `undo_last` takes back what the previous reply did (its journaled effects). Live
  voice: an interruption needs pitched sound (`session._voiced`), so noise no longer
  cuts a reply; `gemini-3.8-live` is the first model tried.
  `APIClient+Blocks` is the only client of `/api/entries|items|schedules|kinds|summary`.
  Siri intents, the share extension, the tasks widget's ✓ (`PATCH /api/items/<id>`),
  Spotlight and the reminder banner buttons all write to the blocks. Focus sessions keep
  their own screen (they drive the Live Activity), opened from Today.
- `Services/` — `GeminiLiveManager` (in-app live voice; one shared call that outlives its screen — `CallBar` over the tabs brings it back, the end button, the Live Activity or sign-out end it), `SpeechManager` (reply playback only),
  `NotificationManager`, `SubscriptionManager`.
- `Localization/` — one `L10n+<Area>.swift` per feature. Arabic/English, RTL/LTR.
- `Widgets/` — home-screen widgets.

The Xcode project is in the repo (`ios/SandyApp.xcodeproj`, with `SandyWidget/`,
`SandyAppTests/`, `SandyAppUITests/`); its targets use synchronized groups, so
there is one copy of the sources and nothing to sync. Build from the Xcode GUI.

---

## 7. Android app

**There is no `android/` directory.** It was removed and the work deferred — the
owner's call, 25 Aug 2026: not its turn yet. This section used to describe four
thousand lines of Kotlin, a tab shell and eight mounted features, none of which
is in the tree.

Nothing depends on it. The backend is transport-agnostic by design (§0), so
whenever Android comes back it mounts the same API the iPhone client already
uses, and the only thing to rebuild is the client.

---

## 8. Data model

Written today, and what reads it:

- **The blocks** — `sandy_entries`, `sandy_items`, `sandy_schedules` (§2.12),
  through `scoped()` on `user_id`.
- **Identity and access** — `sandy_users` (profile, onboarding, persona,
  subscription), `sandy_auth` (login rate limit), `sandy_usage_daily`,
  `sandy_usage_rl`.
- **Conversation** — `sandy_stm`, `sandy_pending_state`, `sandy_prompt_cache`,
  `sandy_cache_stamps`, `conversations` (the app's chat threads, filtered by
  `user_id` by hand in `conversations_api.py`) and `agent_turns` (the send ledger,
  TTL 10 minutes).
- **Hardware** — `sandy_devices`, `sandy_nodes`, `sandy_device_keys`,
  `sandy_scenes`, `sandy_voiceprints`, `sandy_firmware`, `sandy_firmware_chunks`,
  `node_pair_challenges`, `cam_upload_nonces`, `camera_inbox`.
- **Everything else** — `sandy_focus`, `sandy_photos` + the `sandy_photo_files`
  GridFS bucket, `sandy_push_tokens`, `sandy_daily_nudge`, `sandy_nudge_locks`.

**Left in place, no longer written** — the pre-blocks stores, copied into the
blocks by `scripts/migrate_to_blocks.py` and kept until the owner drops them by
hand: `sandy_tasks`, `sandy_reminders`, `sandy_goals`, `sandy_brainstorms`,
`sandy_bs_pending`, `sandy_shopping`, `sandy_habits`, `sandy_habit_log`,
`sandy_expenses`, `sandy_journal`, `sandy_books`, `sandy_reading_sessions`,
`sandy_reading_meta`, `sandy_focus_meta`, `sandy_future_messages`, `sandy_gifts`,
`sandy_shared_content`, `sandy_scene_timers`, `sandy_facts`, `sandy_memories`,
`memory`, `sandy_session_state`, `sandy_activity`, `sandy_evals`,
`sandy_conversations`, `sandy_context_metadata`, `web_chat_history`, and
`guest_usage` (keyed on a guest token's `jti`, not a person). Account deletion
(`features/account_delete.py`) still erases a person's rows in every one of the
others — most by `user_id` or `chat_id`, `web_chat_history` by `_id` — so a
deleted account leaves nothing behind.

Indexes are created at boot on the raw handle — by each store's `init_*` and
`init_blocks`, and by `bootstrap.ensure_indexes()` for the rest (pending state,
prompt cache, camera and pairing TTLs, conversations, focus) — one `try` per
index, so one failure cannot skip the rest. `sandy_stm`'s three are created on
first use by `brain/stm.py::_ensure_stm_indexes`, same one-try-each rule, and
retried until they exist: `(user_id, updated_at desc)` is what keeps the
cross-channel read from scanning every conversation on the server.

---

## 9. Tests and CI

87 test files, pytest + mongomock, no hardware and no live credentials needed.
`tests/test_device_system.py` carries the headline guarantee: the brain may only
act on a **registered** device with a **validated** action, and refuses with the
allowed list rather than guessing. `tests/test_routes_kept.py` pins every route a
client calls; `tests/test_tenant_isolation.py` runs every store through the
isolation contract; the `test_brain_*` files drive the loop with a scripted model.

CI (`.github/workflows/tests.yml`): pytest with coverage → Codecov → `bandit -ll`
→ `ruff check` → a secret scan that fails the build if a `.env`, key, or
service-account JSON is ever tracked.

**CI gates the client and the firmware too**, which §9 used to say it did not:

- `ios` job — `swiftc -typecheck` over every source, driven directly rather than
  through a project file, because the `.xcodeproj` lives in the owner's build
  copy and not in the repo. It catches what actually breaks here: a renamed
  symbol, a wrong type, a missing argument. Then SwiftLint, deliberately after
  the compile — ordered the other way, a long line hid the answer to "does it
  still build?", which is the only question that can block a merge. No
  `--strict`: the rules that crash an app are `error` in `.swiftlint.yml` and do
  stop the build; the rest print as advice.
- `firmware` job — a C declaration-order check and a real `idf.py build` of the
  robot brain, against a placeholder `secrets.h`.

Android has no gate because there is no Android (§7).

Test and lint tooling is pinned in `requirements-dev.txt`, which CI installs
alongside `requirements.txt`. It carries `pyOpenSSL>=23.2.0` — without it
collection dies before the first test on an OpenSSL symbol mismatch
(`AttributeError: module 'lib' has no attribute ...`), which this paragraph used
to ask the next person to fix by hand. Coverage has a floor
(`--cov-fail-under=55`, currently ~68%), and the Codecov upload is skipped on
forks, where `secrets` are not available and it could only fail.

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
  Raw `threading.Thread` is not allowed for it (exempt: long-lived singletons such as the MQTT
  reconnect watchdog and the speaker-model warm-up, and work the request waits on).
- Docs and commit messages in English. Conversation with the owner in Arabic.
- **`docs/` is excluded by `.gitignore`.** Everything in it — the deploy map, the
  hardware inventory, the audit plan, the analysis — exists only on the owner's
  machine and never reaches GitHub. This file lives at the repo root deliberately,
  so it survives a fresh clone.

## 12. Known defects, ranked

Rewritten 25 Aug 2026, re-checked against the code 30 Sep 2026 after phase 5.
Every item was checked against the source, not carried forward — a ranked list
nobody re-reads becomes a way of believing things that stopped being true.
**Ranked by whether a customer can feel it.**

### Reaches a user

0. **Per-board keys: enrolment is limited to the pairing window.** Since 19
   Sep 2026 a paired board still signing with the shared `SANDY_WS_HMAC_KEY` is
   issued its own key in `auth_ok` (`features/device_keys`, NVS `sandy_vkey/k`)
   — but only in the `ENROL_WINDOW_MIN` minutes after the owner pairs (or
   re-pairs) it (`node_store.pair_node` → `open_enrolment`). It then signs
   with it (`"kv": 2`) and the shared key is refused for that board. The camera
   does the same over `/api/cam/upload` (`X-Sandy-Kv: 2`, Preferences
   `sandy_ckey/k`) under its own id `<node>:cam`, so camera and brain never
   share a key. Un-pairing revokes both (`key_unknown`). What is left: inside
   the window, someone holding the shared key who connects as that board first
   gets its key (the real board is then refused — visible, not silent).
   Closing it fully means writing each board's key at flash time.
0b. **Firmware updates.** Since 19 Sep 2026 the brain pulls signed releases
   (`sandy_ota.c`, `features/firmware_store`, `api/firmware_api`): a manifest
   signed with the owner's ECDSA P-256 key (`scripts/firmware_keygen.py`;
   private key off-repo, public key in `main/fw_pubkey.pem`), streamed into the
   idle slot with the size and SHA-256 checked before switching, canary ids
   then a stable percentage (`scripts/publish_firmware.py`), never a downgrade,
   bootloader rollback if the new image cannot reach Wi-Fi. The MQTT `ota`
   command only triggers a check — it no longer takes a URL. Published images
   are always the sale build (`idf.py -B build-retail -DSANDY_RETAIL=1`), which
   compiles `ENABLE_REMOTE` (LAN upload + log on 3333) out; the publish script
   refuses an image that still contains it. The Arduino boards verify TLS
   against `sandy_ca_roots.h` (`scripts/gen_ca_roots.py`). Still open: secure
   boot and flash encryption are off; the Arduino boards are not on this
   update path.
1. **Sentry is wired but only as good as its DSN.** `integrations/error_tracking`
   starts at boot when `SENTRY_DSN` is set; `before_send` strips request
   bodies and, since 19 Sep 2026, log breadcrumbs down to their `[tag]`.
   Without the DSN, failures are still discovered by the owner using the
   product.
2. **The robot's body no longer reacts to what she does.** The celebrate /
   acknowledge / focus melodies and faces were called only by the old goal,
   task, habit and focus tools; the brain never called them, and phase 5 deleted
   the unused `robot_expression` module. The board side (gestures, melodies,
   light effects) is intact; wiring it back means the brain's `list_update`
   (done) and the focus routes calling one small helper.
3. **The brain is not told which devices exist.** `device_control` resolves the
   model's `device` by slug or label and, when nothing matches, refuses with the
   list of the caller's devices so the model can try again — correct, but it can
   cost a model round trip on the first command of a conversation. The fast path
   (§2.3) covers the bare commands.
4. **A POST is never retried, and the chat send is a POST.** `sendWithRetry`
   guards on GET/HEAD because retrying a write could duplicate it, which is
   right — but it means the one dropped packet that motivated the whole change
   is still a red banner on the most-used call in the app. An idempotency key
   on the send is what would close it.
5. **A tool call costs two model calls in series** — the one that picks the tool
   and the one that writes the answer; plain conversation is one. The fast path
   answers a bare device command with none. `[turn] …ms total — brain tools=[…]`
   (§2.11) gives the time per message.

### Real, but nobody hits it today

6. **No staging environment.** Production is what the robot on the desk talks
   to. §1.
7. **`GeminiLiveManager`'s own `URLSession`: fixed.** The call's socket now comes
   from the app's shared `APIClient.session`. (A scene was also sent twice per apply —
   once by `apply_scene`, again by its callers; `apply_scene` alone sends it now.)

8. **Related-memory recall: fixed.** `context.similar_entries` now asks the
   Atlas vector index `entries_vector` (on `sandy_entries.embedding`, filter fields
   `user_id` and `kind`) through `ScopedCollection.vector_search`, which puts the
   tenant in the `$vectorSearch` filter. The index lives in Atlas, not in code: a
   new database needs it created again (1536 dims, cosine). Encrypted rows (moods,
   facts) are never embedded, so they are never found this way.
9. **`submit_background`'s ten workers carry two model calls per turn** (the STM
   summary and the conversation title) with no future ever read. Both go through
   `chat_fn` with `OPENAI_CHAT_TIMEOUT_S`, so a stalled upstream costs a worker
   for that long, not for ever. A sizing question, wanting a measurement first.
10. **`/voice/enroll` has no client.** Speaker verification (§3.2) is off by
   default and there is no screen that records a voiceprint.

### Hardware, and the owner already knows

11. **Two-mic beamforming is not written.** §4.6.
12. **Voice status clips are not flashed** — the sentences are in the table, the
   speaking hook is not written and the partition table has no room reserved. §4.2.

### Checked and closed since the last version of this list

The firmware **is** built in CI (`idf.py build`, §9), so "never compiled" is no
longer true. The control page **exists** (`ios/SandyApp/Features/Control/`). The
room node is **on the per-node topic tree** (§4.5), so `room_device.send()` is
not owner-only any more. The display **has** an Arabic font at 24 and 32 pixels
(`firmware/brain-core/main/fonts/`). `feature_flags.py` (unused) was removed. Servo easing and ten gestures are in
(`sandy_servo.c`). The visitor approval flow and the JSON profile store are gone.
Phase 5 closed three more by deleting what they were about: `tool_health` (no
tool registry left), the 28-round-trip warm turn (the persona-directive build
and the old memory layers are gone), and the router-then-reply pair on every
message (plain chat is one call).
