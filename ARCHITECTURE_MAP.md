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
  servo, an on-board LED, a buzzer and an IR remote. It is one board, the brain,
  and the only one: the camera board and the room node were removed on 14 Oct 2026
  (tag `before-remove-cam-room` holds them).
- **The app** (iPhone) is the same assistant over a different transport, plus
  the control surface for the hardware. Android is deferred — §7.
- **The user's own devices** (lights, an air conditioner, IR gear) are rows in
  the device registry (§2.8) on the robot's outputs, its IR remote above all, so
  she can act on the room beyond her own body.

It is a **multi-tenant product**, not one person's house. Every design decision
below should be read through that lens; where the code still assumes a single
owner, it is called out as a defect, not a style.

---

## 1. Repository layout

```
cloud/                the Python backend — the brain and the API
firmware/             every board's program, one folder each:
  brain-core/         ESP32-S3 robot brain (ESP-IDF, C) — voice, face, servo, IR, MQTT
ios/SandyApp/         SwiftUI iPhone client
tests/                backend tests (pytest + mongomock)
scripts/              migration into the blocks, voice-WS probe, board provisioning,
                      firmware keygen/publish, hardware-doc generator, C checks
docs/                 NOT IN GIT — see §11
```

Three repos exist on the owner's Desktop; only one is worked in. See
`docs/REPOS_AND_DEPLOY.md`.

- `Desktop/Sandy-App` → **this repo**, remote `AlsultanNabeel/sandy-backend`.
- `Desktop/Nabeel/Sandy` → read-only archive of the original single-owner project.
- `Desktop/sandy-web` → the website, a separate repo, deferred.

Deploy target: Heroku app `sandy-robot` (host `sandy-robot-3da0693d32f7.herokuapp.com`), database `sandy-app` (the `MONGODB_DB_NAME` config var; there is no default, and with a database address and no name the server refuses to start, `mongodb_store.init_mongo_connection`). The
Heroku app name is inherited from the old project; the code and data on it are
this one's. Production is also what the robot on the owner's desk is talking to.

**Staging** is a second Heroku app with `APP_ENV=staging` and its own database (the
owner's runbook, kept locally, is `docs/STAGING.md`; the app itself is put off until before
the first real user). `utils/env_guard.py` runs first in `bootstrap.init_runtime`: the
settings before any connection (`check_settings`), the database's mark as soon as it is
open and before any store or the broker (`check`). It refuses to start a staging server
wired to production: the
production database by name (`sandy-app`) or by its mark, production's broker login (host
and `sandy-server` together, or the host inside `SANDY_BROKER_CREDS`), or any `APNS_*`,
`REVENUECAT_WEBHOOK_AUTH` or `SANDY_FIRMWARE_TOKEN`. Each database is marked with the
environment that first booted on it (`sandy_env`, `{_id: "env", env}`), and production
refuses a database marked staging. Problems are named by setting, never by value; a boot
that passes logs one line, `[env_guard] passed: <env>, database <name>`. On
staging `apns.is_configured()` is false whatever is set, and every Sentry event carries
`environment` and an `env` tag.

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
| `app/bootstrap.py` | `init_runtime()` (Mongo on `app.db`, the stores' indexes, MQTT ingest), then `bootstrap()`: `validate_config` (fatal → `RuntimeError`: no database, no chat model, or in prod no valid `SANDY_LTM_KEY`, `ltm_crypto.encryption_ready`, since without it sensitive fields are written as plain text; dev and tests run without it), Google creds, Sentry, `ensure_indexes`, and — on the elected worker — the nudge scheduler and the blocks' indexes + the schedule runner. Idempotent. |
| `app/db.py` | The single Mongo handle. Every store reads through `get_db()`. |
| `app/errors.py` | Typed error taxonomy. |
| `app/brain/` | The agent: the loop, its tools, short-term memory, held confirmations, persona, the fast path (§2.3–§2.5). |
| `app/blocks/` | The data layer — log / lists / schedules + the kinds table (§2.12). |
| `app/api/` | HTTP routes and the `/voice` WebSocket (§2.9). |
| `app/features/` | What is not a block: devices, nodes, scenes, focus, photos, users, usage, speaker id, firmware, device keys, research, weather, image analysis and generation (`vision`), account deletion. |
| `app/integrations/` | Clients for everything external: the chat client (`openai_client.chat_fn`), embeddings, Exa, Places, FLUX/Azure images, Gemini TTS, MQTT (`mqtt_ingest` in, `device_publisher` out), Sentry. |
| `app/services/` | APNs, the `sandy_schedules` runner (once a minute) and the daily-nudge scheduler. |
| `app/utils/` | Tenancy (`tenant_db`, `tenant_version`), `ltm_crypto`, circuit breaker, background thread pool, process leader, profiles, time, Arabic days. Rate limiting lives in `features/usage_store.py` and `api/metering.py`. |

### 2.3 The agent — `app/brain/`

One model call with native tools, in a loop, on the blocks. Chat enters at
`loop.run_turn` (from `api/server.py::_run_authenticated_agent`, shared by
`/api/agent` and `/api/agent/stream`); voice enters at `voice.dispatch` (from
`api/voice_ws/tools.py::_dispatch_tool`). There is no other agent and no flag.

**The turn** (`loop.py`):

1. A held confirmation (`pending_state`, loaded by the route from
   `sandy_pending_state`) is resolved first: yes runs every held call, no cancels,
   a pick answers "which one" (one or several). When a new request follows the
   answer («اه وضيفي خبز»), the model gets the message with a note of what the
   answer settled and does only the rest. Anything else is a normal turn, and the
   question is asked once more at the end of its reply; a second unclear answer
   lets the hold go, so an old yes never fires later. One question is asked at a
   time: a hold that comes while another waits (a pick that still needs a yes and a
   delete in the rest of the line) rides behind it as `then` and is asked once the
   first is answered or let go (`confirm.then` / `confirm.following`), never dropped.
2. **The fast path** (`fast_path.py`): a bare device command («شغّل الضو») is
   matched *whole* against the caller's own registered devices and run with no
   model call at all. The verb must lead and the line must not end in a question
   mark: «التلفزيون شغل؟» or «المكيف وقف» is a question or a report, for the model. It only picks the tool; `device_control`,
   `command_payload` and `tenant_owns_topic` run underneath it unchanged. Its four
   conditions, and why it is not the thing C8 bans, are in `CONVENTIONS.md` C8b.
   `SANDY_FAST_PATH=0` turns it off.
3. `context.build_system` (§2.5), then at most **6** model calls with native tools:
   model → tool calls → results (JSON tool messages) → model, until it answers in
   text. A tool asking for a yes or a choice does not end the turn: the model is
   told it waits and goes on with the rest of the request; every held action joins
   one pending, and the reply is the model's answer to the rest (what the tools did when it
   has none) plus one question, which is ours (nothing of the model's is streamed once
   something is held, and it is told not to say the held action happened).
   When every call of the turn is an answer tool (`loop.ANSWER_TOOLS`: device_control,
   scene_apply, room_restore, image) and each worked with a `reply`, that reply is the
   answer and no second model call restates it. Two or more slow independent calls of one
   step (`loop.SIDE_BY_SIDE`: web_search, weather, recall, summarize, device_state)
   run side by side, each in a copy of the turn's context; the rest run in order.
3b. **Nothing is said to be done that no tool did** (`honesty.py`): a reply that says she
   deleted, removed, added, changed or cancelled («حذفت»، «شلت»، «ضفت»، «عدّلت»، «لغيت», a
   negated one aside: the negation is the verb's own, in its clause, «ما حذفت», «haven't
   added»; a reassurance before it, «لا تقلق، حذفته», «no worries, deleted it», is no
   negation) must have a tool of that kind that worked in the same turn
   (`ctx.worked`, kept by `tools.execute`). The sentence that claims it is taken out and
   what the tools really said goes in its place («ما لقيت…»; a reply the kept text already
   holds is not put in twice), or `NOTHING_DONE`; a held question stays last. On the call her words are heard already, so at the turn's end
   (`session._handle`, `_turn_worked`) she is told to put it right (`honesty.voice_correction`, in the turn's spoken language, a
   turn of its own that she answers). The prompt's own rule is no longer the guarantee.
3d. **A turn does not take back what it just did** (`takeback.py`, asked by `log_delete`,
   `list_delete` and `device_control` themselves, not by `tools.execute`):
   a delete of a row the same turn corrected («no, I meant 60 not 50» → update, then
   delete) and a device switched now the way a schedule of the same turn set it for later
   («turn off the AC in an hour» → schedule, then off now; not when the message asks for it
   now too, «… now and again at 11pm», `takeback._asked_now`) are refused. What the turn
   corrected and set for later is kept as the tools resolved it (`ctx.corrected`, row ids;
   `ctx.for_later`, the device's name and the command it sends), never the model's words: an
   update and a delete with no id name the same newest row, «AC» and «ac» one device. The refusal is for the model alone (an `error`, no `reply`), so the
   honesty check never shows it and the model's answer says what stands.
3c. **The reply is in its message's language** (`lang.py`, `language_guard.py`). A message
   is Arabic when it has a real Arabic word outside a quoted name («ضيفي Nescafe Gold Blend»;
   letters only, `lang.LETTERS`: «؟» or «٢٢» names no language),
   else English when it has Latin letters («add «حليب» to my list»); one with none («2», «👍») or
   only «ok» keeps the conversation's. Every sentence the server says itself (tool replies,
   held questions and summaries, errors, the honesty check's) is a phrase in both languages
   (`lang.PHRASES`, `lang.say` in the turn's language, a context variable). A reply that
   still came in the other language (an Arabic word in an English turn, or mostly English
   words in an Arabic one, or English with no Arabic word at all, «Done ✅»; names aside: «quoted» ones, the message's own words in the other
   script, the names the tools' results carry and those their phrases were filled with
   (`lang.naming`; a tool's reply itself is read, a web summary being the model's words),
   `language_guard.names_of`, and links, numbers and
   Capitalised names in an Arabic reply) is translated once by the model (handed over as text
   to translate: asked to «rewrite» it, the model answered in Arabic), and the rewrite goes
   through the honesty check again (3b); if the rewrite fails the reply goes out as it was. Outside a reply (pushes, the daily nudge, limits, a route's own message)
   the user's own language is used: `sandy_users.language`, which the app sends as `X-Lang`
   (`lang.note` in `require_auth`; a guest's `X-Lang` as it is). Every route's message and
   error, a row's own words (a sealed message, a new chat's title) and the call's own lines
   are phrases; `tests/test_brain_language.py` reads all of `cloud/app` for a literal one
   (a field's value, a module constant, and since 29 Oct what a function gives back or sets:
   «body or "ما قدرت ألخص"» had slipped past), and the prompts and functions the model alone
   reads are named there (`_PROMPTS`, `_PROMPT_FUNCTIONS`).
4. Due `message_to_future_self` schedules (`future.py`) are pasted word for word at the end
   of the reply by the code, never shown to the model, and marked `sent` only when the reply
   went out whole (not an error, not stopped).
5. The turn is written to short-term memory (`stm.save`, with `via`).

**A turn that wrote is never raised.** The app sends a message again under the same
`client_msg_id` when the stream is cut, and the send ledger runs a turn again only when
its first run ended in an error. So once a turn has written anything (`blocks_base.journal`
is not empty), a failure after it is answered with `AFTER_WRITES_REPLY` and the ledger
keeps it as done; the stop and future-self checks after the reply cannot fail the turn
either. A resend never runs its tools a second time
(`tests/test_chat_first_send_and_retry.py`).

**The model call** (`model.py`): the Azure chat deployment through
`openai_client.chat_fn()` — the process's one chat client, behind the `openai`
breaker and the param-quirk adapter — then OpenAI direct (`OPENAI_MODEL`), then
`None` and a fixed error sentence. With no Azure configured the primary already is OpenAI direct
(`openai_client.azure_is_primary`), so there is no second try. Text streams through thread-local hooks
(`model.set_stream_hooks`), cumulative, which `/api/agent/stream` sets on the
thread that runs the turn.

`run_turn` returns `final_response`, `pending_state` (the route saves it for the
next turn) and `execution_result` (image bytes and caption when a tool made one).
The `[turn] …ms total — brain tools=[…]` log line says where a slow turn went.

**The trace** (`features/trace_store.py`): every turn leaves one row in `sandy_traces` —
chat (`loop.run_turn`, its id is the turn's `turn_id`), voice (one per Gemini
`turn_complete`, `voice_ws/session.py`, its tools through `_dispatch_tool(trace=…)`) and
model calls made for a user outside a turn (`trace_store.background`: the STM summary, the
chat title, the daily nudge, photo tags). A row holds the request, the reply, every tool
(arguments, result, ok, ms), every model call (provider, model, tokens in / out / cached,
ms), the cost in dollars (`features/pricing.py`, the one place prices live, dated
`PRICES_UPDATED`), `skills` and `task_id` for the phases that fill them, and `error`.
The tokens are counted at the one client (`openai_client.create_chat_completion`, a
stream asks for them with `stream_options.include_usage`; a call is priced by the model the
reply names, not the Azure deployment's own name, and a model with no price is a warning), on the direct fallback
(`model._openai_direct`) and from the live call's `usage_metadata` (one model call a
voice turn: every message reports the whole context in `prompt_tokens_details`, billed once
a turn, so the input is the largest seen and only the answer's tokens add up; Google's
forum answer, not its reference — check one call against the billing console); tools report from
`tools.execute`. The trace being kept is a context variable (`trace_store.using`), so the
side-by-side tools of one step report into it too. The words — request, reply, tools'
arguments and results — are sealed with `SANDY_LTM_KEY`; without the key none are kept,
only the numbers. Rows expire after thirty days (TTL on `expire_at`), are written under
their user (`ScopedCollection`) and erased with the account. `finish` never raises: a
trace that cannot be written is a warning, never a broken turn. Image generation and
embeddings are not counted yet.

### 2.4 Tools

Nineteen (`tools.py`), voice adds `confirm`, and the robot's call `end_call` (`brain/voice.END_CALL`, handled by the session, not the brain: the call closes once her goodbye has played, `_GOODBYE_MAX_S` at most, and the board reads the clean close as the end; the app has its own end button and is told to point to it; the per-call channel line says only the tool ends a call, «سكّري» alone means it, with a list item it is the list's, unclear she asks). The extra fields are named (`LOG_DATA`,
`LIST_DATA`: amount, category, mood, habit days and time, repeat, qty…), never a
free-form object, which the voice model drops. Enums come from `kinds.KINDS`, so a new
kind needs no tool change.

| Tool | Does |
|---|---|
| `remember` | `entries.add(kind, text, data)`; `kind=mood` keeps a significant mood with the user's words sealed (`ltm_crypto`), once per turn |
| `recall` | entries + items + the user's own pending schedules (reminders, and messages to future self shown sealed until delivered; nudges and scene timers left out), filtered by kind / list / since / until / query words (an alias like «مهامي» becomes the filter); compact rows. Expense rows come with `spending` (total, count, per category over every matching expense of the range, read whole by `entries.each_in_range` rather than the capped rows shown, so the model never adds up); `rang` returns the reminders that already rang (the last day unless a range is given) |
| `list_add` | `items.add`; `due` parsed like `when`; the same open item again is not added: `qty` adds to its quantity («كمان حليب»), a `due` moves it, with neither it is reported |
| `list_update` | by `id` or `match_text` (`matching.match_rows` over the whole list, `items.match_pool`, not one capped page: exact, contained, fuzzy ≥ 0.72; a fuzzy match is only a guess and is never acted on: the tool answers «ما لقيت «X»؛ أقرب إشي «Y»» and the model asks, in `log_update` and `schedule_update` too; a row by no name or id is «ما لقيت», `tools_blocks._not_found`): done / text / due / `no_due` (takes the due off) / priority / `data` merged (habit days and time, qty, repeat) / `move_to` another list. Done on a habit ticks today (a `habit` entry, once a day) and keeps the habit open |
| `log_update` | a log row by `id` (`state_block` shows today's, `facts_block` the facts), `match_text`, or the newest of a `kind`: new text (an encrypted row is sealed again, never embedded), `amount`/`data` merged. A changed fact is updated, not logged again |
| `list_delete`, `log_delete`, `schedule_cancel` | deleting is a tool of its own per block, never a flag on an edit the model can leave out (it once «deleted the last expense» by calling `log_update` with nothing to change). Rows by `id`, several by `ids`, by `match_text` (`all_matching` for every match), the newest of a `kind` for `log_delete` («احذفي آخر مصروف»; «انسي…» for a fact); one row or a few go at once, `everything` (empty a list, a kind, every reminder) or more than five rows wait for one yes (`tools_blocks._remove`). A cancel sets the reminder `cancelled` |
| `schedule` | `schedules.add`; `when` = ISO (one in the past or over a year away is refused, never read as clock words), else the clock words (`when._clock`: a named weekday or «يوم 15» keeps its day, the number after «الساعة» is the hour, «12 الظهر» is noon, morning/evening words match whole words only, and with none, today takes the nearest time ahead while another day reads 1–6 as afternoon and 7–11 as morning), else a bare weekday, else one model call (`when._parse_with_model`), else the deterministic Arabic date parser. `before_id` + `before_minutes` sets it ahead of an existing reminder's or task's time. With `device` + `value` it is a timed device command («طفّي المكيف بعد ساعة»): a `scene` row marked `payload.asked`, shown in the state block and cancellable like a reminder, and never cancelled by a scene |
| `schedule_update` | reminders only: move / rename; `recurrence` changes the repeat, `stop_repeat` ends it, `skip_next` jumps one occurrence (`schedule_runner.next_occurrence`). A reminder that rang in the last two hours (`fired_at`, shown in the state block) can be snoozed through `schedules.snooze`, the notification's «later» route too: a one-time one goes back to pending, a repeating one gets a one-time copy with its payload and its series is left alone |
| `summarize` | the period's entries, items (`items.touched_between`: added or done in it, matched in the database) and schedules as rows; the model writes the summary, nothing is stored; expenses come with `spending`. `week`, `month` and `year` are calendar ones (the week runs Saturday to Friday; the 1st; January) up to today's end |
| `device_control` | a registered device by slug or label, several (`devices`), or every device of a `room`; `by` moves a dimmer from its current level; `command_payload` validates, `send_to_topic` checks the topic is the caller's; an unknown device or action is refused with what is available; a device whose board is gone (`board_gone`, §2.8) is not sent and is told apart as «مش متّصل», and a send the broker refused is «ما اشتغل» |
| `device_state` | reads each device's last sent state, whether it is connected and when it was last heard; changes nothing. The state block lists the devices by name and room |
| `scene_apply` | `scene_store.apply_scene` (keeps the devices' state first, actuates, schedules the reverts, §2.12); a device whose board is gone is passed over, the rest still go, and the reply names it (`offline`), as does `/api/life/scenes/apply` for the app |
| `room_restore` | `scene_store.restore_room`: the devices the last scene changed get the state kept before it (`device_store.before_scene`; IR and screen text are not replayed), its timers are cancelled; once per scene. A device already as the scene sets it keeps what was kept before (`keep_before_scene`), so the same scene twice still puts the room back |
| `web_search` | `features/research.web_answer`: Exa snippets summarised in one model call, with sources |
| `weather` | `features/weather` (the city as itself, nothing appended); with no city, `home_city`: the city the app last showed weather for (`/api/weather` keeps it on `sandy_users.city`); with none saved she asks which city (no default, no guess from the zone; the route answers 400 `city_required`) |
| `image` | `vision.generate_image_with_azure` on the model's own prompt (FLUX, then Azure DALL-E); one a turn, a second is refused (so it never runs side by side) |
| `undo` | «تراجعي»، «لا رجّعيه»، «غلطت رجّعيها» take back the last change (everything one reply, or one tool of a call, wrote), however much was said since; `match_text` one row by name («رجّعي الحليب»), `count` the last that many rows. A deleted row comes back as it was (same id, text, dates, reminder, place in its list), an edited or cancelled one gets its old values, an added one goes; devices are not undone. Read from `blocks.changes`, seven days back |

**A result says whether it happened** (`CONVENTIONS.md` C10): `ok`, `error`,
`reply`; `broke` when the tool raised (`tools.execute` catches it — one tool never
breaks the turn); `needs_confirmation` / `needs_choice` when it will not act yet. An edit
(`list_update`, `log_update`, `schedule_update`) that leaves every row as it was is not a
success: «ما تغيّر شي» (`tools_blocks.NOTHING_CHANGED`), so the model is never told it changed what it did not.

**Confirmation** (`confirm.py`, `pending.py`): one row, or a few named ones, is deleted,
cancelled or changed at once, on chat and voice alike; only a bulk change, more than
`tools_blocks.BULK_ROWS` (5) rows at once, returns `needs_confirmation`;
two matching rows return `needs_choice`. The
loop stores a `brain_confirm` pending (10 minutes, a nonce, `consumed_at`; its
`steps` are every held `{tool, args, summary, ids}` of the turn, `ids` the rows the question
names: a yes acts on those by id (`ctx.held_ids`, `tools_blocks._held_rows`) and never searches
again, so a row added since is not caught, and one gone since is said) and asks «متأكد إنك بدك …؟
(اه/لأ)» or lists the candidates. `confirm.read` is the one yes/no resolver, and it
reads only the opening of the reply: yes/no words, the held action's own verb
(«احذفيها»، «الغيه» for a cancel), filler («متأكد»، «يا ساندي»), and phrases like
«مش مشكلة». «خلص» next to a yes or the verb is «go on», alone it is «drop it»; a
negated verb («لا تحذفها») is a no; cancellation wins a mixed reply; a yes followed by
«بس» is not a yes. A verb is a yes only alone: a verb with more after it and no yes word
(«اعملي تذكير بكرا»، «شيلي الحليب») is a new request, so the hold is dropped (`drop`, the
user is told with `confirm.dropped`) and the message goes to the model. Whatever follows the opening is a new request (`rest`), and the yes does not cover it:
`run_held` marks the turn confirmed only while the held steps run, so a delete in the rest asks again. The rows a pick chooses are one call by `ids` (`confirm.picked_call`), so «كلهم» over
five rows is a bulk change and asks once. `pick`
reads the opening only, like a yes: several («الأولى والتالتة»), a bare number word is that one
(«اتنين» is the second), «الاتنين»/«كلهم» are all, «كل» only as the last word; a number further on
(«ضيفي ٢ بيض») or «كل شي تمام» is not a pick, and a request after the pick goes to the model. On voice there is no text turn to read, so the
`confirm(answer)` tool passes the user's words to the same resolver; holds wait on
the `voice` pending thread, a second hold joins the first, a «which one?» waits there
too and `confirm` takes the pick («الأولى»), and an unclear answer is asked once more,
then let go, as in chat. Holds join through `confirm.add` on both paths: a yes joins the
first question asking for one, a «which one?» waits behind what is already asked.

**On the voice path everything that did not happen is marked**
(`voice._tagged`), because an unmarked refusal is exactly what Gemini reads as
success and confirms to the user: `[فشل التنفيذ]` / `[failed]` for breakage, `[لم يُنفَّذ]` /
`[not done]` for a refusal. Every reply a voice tool gives is a `lang` phrase in the turn's
spoken language: what was heard of the turn so far, else the last turn's (one the noise check kept: an
invented «¿Qué?» sets nothing), else the user's own (`session._spoken_in`, `live_state["lang"]`, passed to `_dispatch_tool(language=…)`). A held action is "not done yet", neither.

### 2.5 Memory

| Layer | Module | Store |
|---|---|---|
| Short-term conversation | `brain/stm.py` | `sandy_stm`, one doc per thread (`<thread>:<user>`), up to 24 messages, TTL 30 days; the model sees all of them (`context.RECENT_TURNS` = `stm.MAX_STM_MESSAGES`, chat and the call alike), so nothing older is lost unseen |
| What she knows | `brain/context.py` | `fact` entries with their ids (the newest 30 distinct ones of two words or more; anything still ciphertext is left out) and the onboarding profile (`sandy_users.onboarding`: name, interests, notes, daily-question answers) |
| What is open now | `brain/context.py::state_block` | open items per list (the soonest due and the newest, so a long list hides neither), pending reminders and today's log (not facts, moods, habit ticks or summaries), reminders that rang in the last two hours, with their ids and times in the user's zone, so a vague mention is resolved by the model and edited by id (messages to future self stay out) |
| Related past | `brain/context.py::similar_entries` | nothing for a message under three words; else the 8 nearest entries that are not facts, chat summaries or habit ticks, from the Atlas vector index `entries_vector` (tenant in its filter); text search when there is no vector or no hit |
| Conversation summaries | `brain/stm.py::_summarize` | one `summary` entry (`data.thread_id`) per conversation, in the background: when a message comes after a 30-minute pause, or when a thread passes 24 messages and drops to its newest 12; turns are marked `summarized` so none is summarised twice. The chat prompt carries them (`context.conversation_block`): this thread's newest two, oldest first, and the two other conversations closest to the message (same embedding as the related entries, three words or more) |
| Held actions | `brain/pending.py` | `sandy_pending_state`, keyed `<chat_id>:<thread_id>`, TTL 1 hour |
| What was changed | `blocks/changes.py` | `sandy_changes`, TTL seven days on `at`: every delete, from anywhere (the app's screens too), keeps the row as it was, so a delete is soft: the row leaves its list at once and waits there, marked deleted, until the TTL takes it; while Sandy's turn runs (`changes.recording(ctx.turn_id)`, chat per reply, a call per Gemini turn) her adds and edits are kept with it. What `undo` reads; `_base.noted` writes it |

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
(`with_recent_turns`). That per-session part (the clock, time since the last message, his devices by name and room,
the recent turns) is
built on a pool thread inside the caller's own profile (`memory.session_context_for`), so the
clock is in their zone; built on the loop with no user active it read Cairo time. `utils/tenant_version.VERSIONED` names the collections it
is built from (`sandy_users`, `sandy_entries`): a write there through `scoped()`
bumps the version, and `prompt_prewarm` rebuilds it in the background for tenants
who use voice. «Reset my data» erases around `scoped()`, so it bumps the version and
stamps `corrected_at` itself (`account_delete.wipe_account_data`). Bump `_PROMPT_REV` when the cached text changes shape.
There are two texts per version, one per speaker-gate state (`speaker.speaker_gate(user, channel)`:
the robot's guarded one once a voiceprint exists, the trusting one for the app's call), kept
apart in both caches (`_variant`). The build takes the call's channel as an argument (the robot
when none is given, which is what the prewarm builds): it runs on a pool thread, where the
session's channel never arrives, and reading it from there handed the owner's own phone call
the stranger persona.
While a moved version is rebuilt, the last instruction (up to six hours old) serves the
call, except one built before the tenant's facts last changed: editing or removing a
`fact` entry (`entries.update` / `delete`, or an undo touching one) stamps
`corrected_at` on the tenant's version (`tenant_version.mark_corrected`), as does
changing the name, the get-to-know-you answers or the persona (`users_store.set_onboarding`,
`record_nudge_answer`, `set_persona`), and
`_shared_latest` serves nothing older, so «انسي…» or a corrected fact never reaches the
next call.

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
request sets a tenant. Indexes lead with the tenant field (`user_id`, or `chat_id` on the older collections),
except `sandy_schedules`' `(status, fire_at)`, which serves the runner's scan across every tenant.
Sent, failed and cancelled schedules are kept for good (the owner's decision); that index keeps the
scan to the pending rows however many there are.

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
  device in the calling tenant's registry, on a node the tenant still has paired?"* The
  tenant-scoped reads are the enforcement — another tenant's topic simply is not in this
  tenant's collection, and a device row left behind by a release that stopped halfway
  drives nothing. A release (`node_store.unpair_node`) whose device delete fails stops
  before the node row goes (`release_failed`, 503) so asking again finishes it.
- **`device_publisher.send_to_topic()`** (`integrations/device_publisher.py`, the
  server's one publisher) gates on that. Every registry-driven path goes through it: the
  `device_control` tool, `/api/devices/<name>/control`, IR learn, and scene actuation.
  A node's service channels (`wifi`, `screen_img`, `factory_reset`, `pair_code`, named one
  by one) go through `publish_service`, whose caller checks the node is the tenant's.
- **Scenes written in the old words** («light», «music», «fan», «curtain», «color», «buzzer»,
  saved before devices were rows) are read at apply time (`scene_store._resolve`, `_LEGACY`):
  «buzzer» is the tenant's one device on that output; the rest name nothing a board has (the
  light and the music were the room node's), so they are passed over and the result names them
  (`skipped`), and the rest of the scene still runs. Two devices on one output is passed over
  rather than guessed. `list_scenes` shows the words as the devices they mean, so the app's
  editor offers and saves real devices only. Nothing seeds scenes any more: the built-ins every
  account was given were all the room node's light and music; the rows already seeded are the
  user's, deleted like any other.

### 2.8 Device registry

`app/features/device_store.py`. The stated principle, and it is a good one:

> Devices are **data, not code**. Each tenant owns a list. Adding a device is a
> row, never new code per device.

- Control types: `switch`, `dimmer`, `enum`, `media`, `cover`, `ir`, `text` (free text for her screen, limited by `meta.max_bytes`, default 255). A dimmer with `meta.levels_only` (every catalogued one: the neck, the gains, the volume) takes a number only; «on»/«off» is refused with its range and the app draws no switch.
- `command_payload(device, action, value)` is the **only** validator. It returns
  the payload or refuses with the list of allowed values so Sandy asks instead of
  guessing. This is what ends "turn the light on → applied the off scene".
- One transport: `{"kind":"node","node_id":…,"output":…}`, an output on a node the tenant
  paired. The raw `mqtt` topic (any tenant could publish anywhere outside the node tree on the
  server's own broker login) and `wifi_api` (never sent at all) were removed; a row saved with
  either is still listed, reaches nothing (`device_topic` is None, Sandy says it is no longer
  supported), and the app shows it as «not supported» with a delete.
- A device's `online` is not stored: every read takes it from the board behind it
  (`node_store.part_present`: the brain's `online` and not in safe mode; a board never heard
  from is not connected). A board that said it went sets `board_gone`, and nothing is sent to
  it: the board holds a clean session, so the broker would take the command and drop it.
  `/api/devices/<name>/control` answers it 409 `device_offline`, apart from a send the broker
  refused (200, `sent: false`).
- **A retired board's rows are passed over, never deleted** (`node_store.retired_output`: an
  output under a branch, `cam/…` or `room/…`). The device rows of the camera and the room node
  stay in `sandy_devices`, and every read (`list_devices`, `get_device`, `get_devices`,
  `devices_on_output`) skips them, `device_topic` is None for them and `tenant_owns_topic`
  refuses their topics; a new device on such an output is refused. A node's stored outputs and
  `cam_*` / `room_*` fields are not shown (`node_store._public`) and go at its next heartbeat.
- A device's `state` is the last command sent (`set_state`, with `state_at`) or what the
  brain's heartbeat says (`node_provision.board_states`: `volume`, `mic_*_gain` as levels,
  `mic_*` on unless `mic_*_muted`, written by `device_store.set_board_states`), so a relative
  «a little lower» starts from the real volume. A command's state stands
  `BOARD_STATE_GRACE_S` (15 s) against a heartbeat, which may have left the board before it.
- Every topic the server publishes a device on is `sandy/node/<id>/<output>` of a node the
  caller paired; `tenant_owns_topic` matches nothing outside that tree.
- **One robot per account** (the owner's decision): pairing a board when the account
  already has another answers 409 `one_robot` before any presence code is sent, and the
  unique index `one_robot_per_account` on `sandy_nodes.user_id` closes the race. An
  account that already had two when the index came is logged at boot, not unpaired.
- **A board nobody paired is heard** (`node_sightings`, keyed by board, a day TTL): its
  heartbeat, otherwise dropped, records that it is there. Pairing sends the presence code
  only to a board heard within `PRESENT_WITHIN` (30 s), that did not say it went and is not
  in safe mode (`node_store.unpaired_board_present`); otherwise 409 `not_connected`, and
  the app says to turn it on and put it on the home network.
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

85 HTTP route handlers on 68 paths, plus two WebSockets (`/voice`, `/voice/enroll`).
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
  (control, IR learn, pairing, Wi-Fi), `/api/life/focus` (+ start /
  stop / history), `/api/life/scenes` (+ actions / apply / delete), photos
  (+ albums, file; `GET /api/photos` is a page of 200 newest first with `next` to pass back as `before`,
  its text search and the album counts run over the whole album in the database), images (`/api/image`, `/api/image/edit`, `/api/analyze-image`),
  `/api/research`, `/api/weather`, `/api/persona`, `/api/onboarding`,
  `/api/features`, `/api/subscription`, push register / unregister,
  `/api/voice/tts`, and the `/voice` socket for live calls. The share extension
  uses `/api/agent`, `/api/analyze-image`, `/api/photos`, `/api/entries` and
  `/api/items`. `/api/features` answers `{hidden, on}`: what the owner hid app-wide
  (`SANDY_HIDDEN_FEATURES`) and the feature switches on for the caller (`utils/flags.py`:
  `SANDY_FLAGS`, a JSON object, `"all"` or a list of account ids per switch; missing or
  unreadable is off; `flags.on(name, user_id)` is the one way the code asks).
- **The owner** (`api/owner_api.py`, the accounts in `SANDY_OWNER_ACCOUNTS`; anyone else
  404) — `GET /api/owner/traces?limit=&user=&source=` (newest first, never words),
  `GET /api/owner/traces/<id>` (one turn; its words opened only when it is the owner's
  own turn) and `GET /api/owner/costs?days=30` (`{days, total_usd, by_user, by_source,
  by_task}`). These are the one deliberate read across tenants.
- **The robot** — `/voice`, `/api/firmware/manifest` and `/api/firmware/image/<version>`
  (OTA; a `board` other than `brain` is a retired camera or room board asking, refused 400,
  never handed the brain's image). The camera's routes (the snapshot pair, `/api/cam/upload`)
  and the light arm's went with those boards; `tests/test_routes_kept.py` pins them as gone.
- **The owner's tooling** — `/api/firmware/publish` and `/rollout`
  (`scripts/publish_firmware.py`), `/api/diagnose` and `/health` (by hand).
- **RevenueCat** — `/webhook/revenuecat`. Events are saved in the order they happened
  (`subscription.event_at`; an older one is acknowledged and dropped), a trial's expiry is an
  expiry, `BILLING_ISSUE` keeps access three days from the event, an unknown user is
  acknowledged and logged, and a failed save answers 500 so the event comes again.
- `/voice/enroll` (socket) records a voiceprint from the laptop script; the app's
  Robot › «صوتي» screen uses `POST /api/voice/enroll` instead and records on the robot (§3.2).

**The blocks** (`api/blocks_api.py`, §2.12) — every route `require_tenant` except
`/api/kinds` (`require_auth`), so the block stores' scoped handles do the
isolation; a bad input is 400 `{"error": <code>, "message": <Arabic>}`, text
capped at 2000 characters and `data`/`payload` at 8000 of JSON:

| Route | Does |
|---|---|
| `GET/POST /api/entries`, `PATCH/DELETE /api/entries/<id>` | the log; `GET` filters `kind`, `since`, `until`, `q`, `limit` |
| `GET/POST /api/items`, `PATCH/DELETE /api/items/<id>` | the lists; `GET` filters `list`, `done`, `q`, `limit`, a page at a time: an open list oldest first, the done half newest first, `next` when more follow (pass it back as `cursor`; the app reads an open list whole, the done half's newest page); `PATCH {"due": null}` clears it |
| `GET /api/items/lists` | every list name the user has rows in (project lists come from here) |
| `GET/POST /api/schedules`, `PATCH/DELETE /api/schedules/<id>` | anything that fires; `GET` filters `kind`, `from`, `to`, `status`, `limit`; `fire_at` must be future; `recurrence` is daily/weekly/monthly/yearly or an RRULE (read by the runner's own parser, `when.recurrence_rule`); the app may set status only to `pending`/`cancelled` |
| `POST /api/schedules/armed` | `{token, ids, once?}` (at most 500): the phone with this push token (one of the caller's, else 400 `unknown_token`) has these reminders scheduled itself and no others (`schedules.arm`: added to each row's `armed`, taken off the rest); a repeat in `once` is held there for its next ring only (`armed_once`: when the runner moves it on, that token leaves `armed`, so the rings after it are pushed); answers `{ok, armed}` (rows matched) |
| `POST /api/schedules/<id>/snooze` | `{minutes}` (1–1440), `id` optional: a reminder rings again that long from now (`schedules.snooze`, shared with `schedule_update`): a one-off goes back to pending at the new time, a repeat gets a one-time copy with its payload (under the phone's `id` when given, so an offline snooze knows what will ring and a resend answers the copy already made; another user's id is 409 `id_taken`) and its series is left alone; answers the row that will ring (`id`, `item`); a cancelled or unknown one is 404 |
| `GET /api/kinds` | `kinds.KINDS` as `{name, block, labels:{ar,en}, icon, prefix, fields:{name: type}}` — the app builds its screens from it |
| `GET /api/stats` | My Life's numbers over the whole log in the user's zone: entries per day for 30 days, and this month's spending (in all and `by_category`), habit check-ins and entries (summaries left out), plus the monthly `budget`; the app adds what it made since |
| `POST /api/undo` | `{turn}`: the «تراجع» under a reply puts back what that reply deleted or changed (`changes.of_turn`, `changes.undo`); 404 `nothing_to_undo` once nothing of it is left, or for another user's turn. A chat reply that deleted or changed rows carries `undo: {turn, label}` (`loop._undo_offer`; an add alone offers none) |
| `POST /api/budget` | `{amount}`: the monthly spending limit on `sandy_users.budget` (0 removes it); the app rings at 80% and 100%, and `remember` of an expense tells the model past 80% |
| (expense category) | an expense saved with no `data.category` (app sheet on "automatic", or Sandy leaving it out) gets one from its words in the background (`brain/categorize.py`, one short model call; "other" when no model) |
| `POST /api/summary` | `{period, focus?}` → `{text, count}`: the brain's `summarize` rows, one model call (`brain/summary.py`); metered; nothing recorded → a fixed sentence, no call |

Datetimes go out as ISO in the user's zone and come in as ISO (naive = user's
zone; a bare date in `until`/`to` covers its day). **The user's zone is their own**
(`utils/time.py`): the app sends `X-Timezone` (the phone's IANA zone) on every
signed-in call, `require_auth` keeps it on `sandy_users.timezone` when it changed,
and `USER_TZ` is one tzinfo that answers with the active tenant's zone (cached a
minute; `USER_TIMEZONE` when none is known), in requests and in the background
runners, which run inside the tenant's context. When the zone changes, every pending
repeat is moved to its next time on the new clock (`schedule_runner.follow_zone`, the
claim's compare-and-set); a one-off keeps its moment. A row with `encrypted` in its
`data`/`payload` is decrypted for its owner and re-sealed on edit; a
`message_to_future_self` is sealed at rest.

**Every route that spends money on a provider is metered** through
`api/metering.py` — the chat routes, image generation and analysis, web and
place search, photo tagging, attachment uploads and `/api/summary`, one unit each against the
caller's tier. Image analysis is checked first (`metering.over_limit`, nothing counted) and charged only
once it worked; a failed one answers 502 `vision_failed`. A new paid route calls `meter_claims`.

**No route issues a guest token.** `make_token` still honours a `guest` role;
chat and images refuse one with 403, `require_tenant` routes refuse it, and the
rest resolve it to an empty tenant.

### 2.10 Auth

`api/auth_handlers.py`. JWT, HS256. Owner tokens 7 days, guest 48 hours. A signed-in
token carries its account's generation (`gen`, `sandy_users.token_gen`, 0 until it moves;
moving it is how tokens are revoked). A signed-in token is honoured — by `require_auth` and the
`/voice` JWT hello alike (`auth_handlers.account_allows`) — only while its account exists on that
generation: the answer is kept a minute per account (`GENERATION_TTL_S`), forgotten at once when the
account is deleted (`forget_generation`; the other workers within the minute); a read that fails
serves the last answer kept, and with none the request goes through rather than signing everyone out.
Deleting an account moves it first (`account_delete.revoke_sessions`, before the robots are
released or a row goes; a store that cannot move it answers 503 `unavailable` and nothing is
touched), so a delete that stops halfway leaves no live token: the user signs in again to finish it.
There is no server sign-out or password change yet; when one is added it moves the generation and
calls `forget_generation`. Once a day old it comes back renewed in the
`X-Sandy-Token` header of any `require_auth` response (`renewed_token`), on the same
generation only: a revoked token, a deleted account or an expired token is never renewed,
so a session in use does not end, and one left a week unused does. The app keeps the new
token when it is still the one it sent. Email sign-in counts failed attempts only,
in a 15-minute window, three ways (`auth_handlers.EMAIL_LOGIN_LIMITS`): 5 per email and
address, 20 per address, 20 per email alone — so a stranger's guesses never keep the owner
out and a new address per guess does not guess without end. Registration and pairing keep
`check_rate_limit` (every attempt). Both fall back to an in-process sliding window when
Mongo is down. `JWT_SECRET` has no default —
an empty secret would let anyone forge a token, so it refuses rather than degrade.

### 2.11 External services

The chat model is `openai_client.chat_fn()`: Azure OpenAI (`AZURE_OPENAI_CHAT_DEPLOYMENT`)
when the Azure trio is set, else OpenAI direct; the brain falls back to OpenAI
direct (`OPENAI_MODEL`) when the primary call fails. Every other model call —
the conversation title, the STM summary, the daily agenda line, image analysis
and photo tagging, the web-search summary, the time parser — uses the same client.
Speech-to-text on the voice path is Gemini Live's own input transcription. TTS
(`/api/voice/tts`) is Gemini only. Images are Azure FLUX with an Azure OpenAI image
fallback, taken only when FLUX failed, not when it timed out (`azure_flux.FluxTimedOut`: it may still be
drawing and billing, and a second sixty seconds is past the worker's limit). Embeddings are Azure (`AZURE_OPENAI_EMBEDDING_DEPLOYMENT`) or OpenAI
direct. Research is Exa; places are Google Places. Push is APNs over HTTP/2 (`h2`
is in `requirements.txt` for exactly this). MQTT is HiveMQ Cloud over TLS.

Circuit breakers (`utils/circuit_breaker.py`) wrap `openai_client`, `exa_client`,
`gemini_tts` and `features/weather`. Not wrapped: `azure_flux`, `azure_image`,
`google_places`, `services/apns`, `embeddings`.
A breaker counts only outages (`circuit_breaker.counts_as_outage`: no connection, a timeout,
a 5xx or a 429). A 4xx is the provider answering that one request was wrong (a content
filter, a prompt too long) and counts as the service being up.

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
| `blocks/schedules.py` | `sandy_schedules` | SCHEDULES — anything that fires: `{kind, text, fire_at, recurrence (RRULE), series_start, payload, status, migrated_from}` |
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
(`status` pending, `fire_at` ≤ now, no live claim) is claimed by a compare-and-set on its
own `(status, fire_at, claimed_until)`: the claim marks it being fired (`claimed_until`, five
minutes ahead, and `fire_tries`) while it stays `pending`, so every screen, the brain and the
summaries read it as pending with no change. Only the worker whose update matched fires it, so
nothing fires twice across workers or dynos. Then it is settled: a one-off moves to `sent`, a
recurring one to its next RRULE time (anchored in local time, so "every day at 8" survives DST),
and the claim goes. A worker killed in between leaves the claim to lapse and a later tick fires
it; a row claimed three times without settling (`MAX_FIRE_TRIES`) is marked `failed` with a log
line. `fired_at` and `last_error` are set on the row. A repeating row keeps where its
series began (`series_start`, the wall time on the user's clock with no zone, set on add
and on a new time or repeat, kept by a skipped occurrence; a row saved before it existed
gets it at its next ring), and the next time is counted from there, so «three days» ends
after three and «every day at 8» is eight on the user's clock across a DST change.

| Kind | Firing |
|---|---|
| `reminder` | The phone rings it locally from `GET /api/schedules` and tells the server which it scheduled (`POST /api/schedules/armed`, the row's `armed` push tokens; a new time or repeat empties it). The set is what is really pending on the phone after it schedules (`NotificationManager.rearm`: reminders, tasks and habits together, nearest first under `itemBudget` (50) requests of the system's sixty-four, an alarm counting three; what did not fit is not in the set, so the server pushes it), a repeat whose first time is later than its own trigger would first match («every day from next Monday») scheduled as that one ring and sent in `once`, sent a second after a burst of changes and again once the push token is registered; signing out sends an empty one before the token goes (`NotificationManager.leave`); «later» on the phone, from a banner or a screen, goes through the outbox to the snooze route with the copy's id made on the phone (`SchedulesStore.snoozed`), and a repeat keeps its own repeating notification; and a server push of `kind` `reminder` opens the reminders. The server pushes over APNs, when `services/apns.py` is configured, only to the user's phones that did not arm it, unless the row is more than 15 minutes late; the push carries the phone's reminder category (`SANDY_REMINDER`) and keys (`reminder_id`, `reminder_recurrence`, `alarm`, `alarm_focus`), so «later» and «done» work on it. `failed` only when a phone was left to push to and none took it. The user's robot rings it too when it is on (`_ring_robot`: the `alert` melody on its `buzzer` and «⏰ text» on its `screen`, through `send_to_topic`; only the screen in quiet hours, nothing with reminders off or when 15 minutes late); the board needs nothing new for it. |
| `scene` | A scene's timed revert, or a timed device command the user asked for (`payload.asked`): `scene_store.apply_scene` cancels the tenant's pending revert rows (not the asked ones) and writes one per `for_min` action; the runner sends it through `scene_store._actuate` (room words read as in §2.7), and a miss retries a minute later up to `MAX_TIMER_TRIES`, then `failed`. |
| `daily_nudge`, `summary_nudge` | push text only; `failed` when no device took it (no APNs, no token, every send refused). |
| `message_to_future_self` | not fired here: the next chat reply delivers it (§2.3). |

**The phone hears of every change** (`services/schedule_sync.py`): a reminder added, changed or
deleted through `blocks/schedules.py` (the robot, the app's call, Sandy in chat, the routes), put
back or taken away by an undo, sends the user's phones a silent background push
(`apns.send_background`, `{"sync": "schedules"}`, changes two seconds apart go as one), so a
reminder made away from the phone is scheduled there (the app's `remote-notification` background mode; `AppDelegate` reloads the reminders through `SchedulesStore.reloadReminders`, which schedules them and arms them). The app also reloads them each time it comes back to the front, and the end of its own call posts `sandyBlocksChanged`. Idle without push keys. Apple may hold a
silent push and never wakes an app the user swiped away; the visible fallback for that is below.

A recurring row that fails stays armed for its next time with `last_error`. A
migrated row more than 15 minutes late is settled without firing: its old store
already fired it, and the migrated scene timers in particular were never marked,
so replaying them would switch lights hours later.

The daily nudge push itself still runs on its own scheduler
(`services/nudge_scheduler.py`: every quarter hour, to each user whose own clock is in the
eight o'clock hour, once per user and local day by a Mongo lock, quiet hours read inside
their context so on their clock);
`/api/daily-nudge` builds the day's nudge from the blocks (open tasks, overdue,
pending reminders) and the last STM turn ("was up late").

### 2.13 `app/brain/`, file by file

| Module | Holds |
|---|---|
| `loop.py` | `run_turn`: held action → fast path → context → model/tool loop → future-self delivery → STM save |
| `model.py` | the model call (Azure via `chat_fn`, then OpenAI direct), streaming, the stream hooks |
| `tools.py` | the tool table (JSON schemas from `kinds.KINDS`), `declarations()` for Gemini Live, `execute()` |
| `tools_blocks.py` | `remember`, `recall`, `summarize`, `list_add`, `list_update`, `schedule`, `schedule_update` |
| `tools_world.py` | `device_control`, `device_state`, `scene_apply`, `room_restore`, `web_search`, `weather`, `image` |
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
| `takeback.py` | a call that would take back what the same turn did (3d), refused to the model |

The speaker gate (`SANDY_REQUIRE_SPEAKER_AUTH`, §3.2) guards the brain's
destructive voice calls (`speaker._is_sensitive_call`).
The gate is read once per session, on a pool thread beside the instruction build
(`speaker_gate(user, channel)` in `_live_session`'s gather), and handed to the audio loop
(`verify`) and the reply loop (`gate_on`); nothing on either loop reads the voiceprint again.

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

**Her face follows what she says, on the robot only** (`voice_ws/face.py`). As her
transcript streams in, `face.mood_of` reads its mood from words (no model call) and the
server sends `{"type":"mood","mood":"<name>"}` whenever it changes; `end_turn` carries
the mood of the whole reply (`"mood"`, `happy` when nothing stands out) for the face she
keeps a moment after speaking. The names are the firmware's `MOOD_MAP`
(`sandy_face.c::face_mood_by_name`, shared with the broker's `mood` command;
`tests/test_voice_face.py` pins that). The board (0.11.6 on) talks with the latest
`mood` frame's face (happy until one comes), and once playback ends holds the
`end_turn` face for `AFTER_FACE_MS` (2.5 s) before listening again; a barge-in drops
both. Firmware that predates it ignores both frames.

**While a tool runs** (a search, a picture), the server sends `{"type":"working"}` to the
device at once and every `_WORKING_EVERY_S` (3 s) until the tool calls return: the app shows a
line, and the robot keeps the call open on each (`VOICE_WORKING_MAX_MS`, 60 s, at most), since
its eight-second idle limit used to close a call before a slow tool's answer.

**Not every voice is a turn** (`voice_ws/noise.py`, the robot's call, in any language): a voice
under `NEAR_FACTOR` (40%) of his own level in this call (the median of his last turns) is far
talk or the TV and opens no turn, so nothing reaches Gemini and the quiet clock runs on. A turn
that was quiet (under 60%) or very short (under 400 ms of voice) is `suspect`: her reply is held
until its transcript shows it is not a recogniser's stock phrase for noise («¿Qué?», «Gracias»,
«شكرا على المشاهدة»); when that phrase is the whole turn the reply is never played, the turn is
not kept and the quiet clock is put back. Gemini Live gives no confidence or no-speech
probability for its transcript, so none is used.

**A call ends by itself on the server too** (`session._call_watchdog`), for the robot and the
app alike: `call_idle` after `SANDY_CALL_IDLE_S` (90 s) with neither a turn she understood (`understood_at`:
words in its transcript, not dropped by `noise`, so a TV in the room does not hold it) nor her voice, and `call_time_limit` at `SANDY_CALL_MAX_MIN`
(20 min). The deadline is set once per call, so a GoAway reconnect neither resets nor extends it;
the reason goes to the device as `{"type":"error","msg":…}` (the app shows a sentence,
`GeminiLiveManager.errorLine`; the board logs it and stays unlocked).
**Voice has a daily allowance in minutes** (`metering.voice_seconds_left`): `SANDY_CALL_MINUTES_FREE`
(10) or, for a subscriber or an account named in `SANDY_OWNER_ACCOUNTS` (user ids; the account,
never the way it signed in), `SANDY_CALL_MINUTES_SUBSCRIBER` (60), counted in seconds on
the day's usage row (`usage_store.add_voice_seconds`). A call checks it at the start (none left →
`call_minutes_exceeded`), ends when it runs out, and adds its length when it ends; a robot's call
counts on its owner's account. A board nobody paired gets no call at all: `_live_session` answers
`{"type":"error","msg":"not_paired"}` before Gemini opens, and the board says so itself (status
`NOT_PAIRED`, part `IDENTITY`, a tone and a confused face), asking again on the next wake word. `/api/voice/tts` spends the same
minutes (the WAV's length) and answers 429 `call_minutes_exceeded` when they are gone.

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
| `not_paired` | after `auth_ok`: no account has paired this board, so no call opens (nothing is billed); the board shows `NOT_PAIRED` and asks again on the next wake word, no backoff |
| `server_error` | the server's fault, not the board's: a key record it cannot decrypt (`device_keys.KeyUnreadable`, a wrong or changed `SANDY_LTM_KEY`), any other failure on its side during the handshake (a database read), or no Gemini key. `bad_handshake` is kept for a hello that does not parse. The board keeps its key, is not locked out, and ends the call at once (status `NO_SERVER`) |

The `ts` must be wall-clock, so the firmware opens no session until SNTP has set the clock
(`sandy_clock.c`, started by `app_main`'s loop once Wi-Fi is up, safe mode too, where a signed erase is checked against it: the router first, then three public servers; never blocking). A wake word
before that gets a local cue and status `NO_CLOCK` (part `CLOCK`), shown on its own after a
minute unset. `replay` resyncs the clock and ends the call, with no ten-minute lockout —
that backoff is for the key refusals only.
Control messages are assembled whole (`s_rx_text`, 2 KB PSRAM) across frames and events
before they are read; a continuation (`0x0`) belongs to the frame type before it, so a split
text message is never played as audio.
A board that cannot reach a time server will sit there forever while the wake word
keeps working — that failure looks exactly like a dead network.

Three ways in, checked in this order: a legacy plain-text secret (dev/echo tests),
a browser JWT (`{"type":"hello","token":…}`, any signed-in account; guests are
refused), then the device HMAC. With no key configured at all it refuses unless
`SANDY_WS_ALLOW_OPEN=1`, so a missing env var in production cannot leave the
socket open.

`_authenticate` clears the session identity and channel before it reads anything:
the server thread is reused between connections and the identity is a context
variable on it, so a board nobody paired yet used to speak as the last caller.

You can probe all of this from a browser without hardware — see §10.

### 3.2 Speaker verification

`features/speaker_id.py` + `voice_ws/speaker.py`. CAM++ via sherpa-onnx, running
locally: no account, no torch. On for robot sessions once the owner's voice is known
(`speaker._speaker_gate_enabled`: a voiceprint exists, or `SANDY_REQUIRE_SPEAKER_AUTH=1`),
never on the app's call (the phone is signed in, and its mic is not the print's). Each
closed turn is checked and the persona injected: the owner gets her whole self, anyone
else a kind, neutral Sandy with nothing private. It also guards the sensitive calls (`speaker._is_sensitive_call`):
`list_delete`, `log_delete`, `schedule_cancel`, an edit with `all_matching`,
`schedule` of a `message_to_future_self`, and `confirm` (which only runs a held
delete or bulk change). With no voiceprint enrolled it allows — it does not lock
the owner out before enrolment. A voiceprint on record that cannot be read (`SANDY_BIO_KEY` missing or changed) or a
lookup that failed is not «none» (`speaker_id.has_profile`): the gate stays on and verification says no. When the speaker model is not loaded (a
failed download is retried after 30 s, doubling to 30 min, `speaker_id._get_extractor`) `_verify_owner` answers None, «cannot check»: no sensitive call runs and nothing private is
said, but the owner is not called a stranger. The voiceprint is learned from the robot's own mic: the
app (Robot › «صوتي») calls `POST /api/voice/enroll`, and the next five robot turns of three
seconds or more are its clips (`sandy_voice_enroll`, deleted once the print is built; a
fifteen-minute window, after which a TTL index on `until` removes them even if the robot
never speaks again; account deletion and reset remove them too); she says so in her reply. It is stored only encrypted
(`SANDY_BIO_KEY`). The older `/voice/enroll` socket (the laptop script) still records one.

---

## 4. The firmware — robot brain

`firmware/brain-core/`, ESP-IDF, ESP32-S3. `sandy_voice.c` is about 2000 lines and is
where the difficulty lives.

| File | Does |
|---|---|
| `sandy_main.c` | boot order; each init wrapped in `TRY_INIT` so one failure never boot-loops the board |
| `sandy_voice.c` | the esp-sr audio front end (input "MMR": both mics and the speaker reference; echo cancelling, two-mic separation, voice detection and the wake word in one pipeline), local commands, the WS link, the uplink buffer, the session manager. `mic_task` reads both mics (a 200 Hz high-pass, `VOICE_MIC_HPF_HZ`: the Wi-Fi's transmit bursts reach the left mic as a rumble under 300 Hz that the detector took for speech), pairs each sample with the reference and queues them; `feed_task` hands them to the front end (its `feed()` does the echo cancelling, about two thirds of a core) and `proc_task` reads it: only speech goes up (plus the detector's cached onset). She is stopped by a voice only over her audible playing, after she has played `VOICE_BARGE_AFTER_MS` in the call (the cancelling has not learned the room before), for `VOICE_BARGE_MS` unbroken at `VOICE_BARGE_PCT` of the caller's own loudness; then the board silences her at once and sends `{"type":"barge_in"}`, which the server trusts for `_BARGE_TRUST_S` instead of its own bar. **CPU:** 240 MHz (at 160 the mic lost 14% of its samples); core 1 carries the amp, the mics and the feed, core 0 Wi-Fi, TLS, the socket task (pinned there), the uplink, the front-end reader and the face. While an image is written to flash (`voice_hold_for_update`: the LAN upload and `sandy_ota.c`) the feed pauses, or the starved tasks tripped the watchdog. The playback cushion carries over between calls (starts at 300 ms). The echo reference is every sample handed to the amp, which never stops (`spk_task` writes silence between replies), kept in a ring by its number on the amp's clock; `mic_task` pairs each mic sample with the one played as it was heard (`ref_measure`, from both I2S clocks, re-measured as each call opens) plus `VOICE_REF_LEAD_MS`. It used to take whatever was queued, which slid up to 300 ms behind the echo at every pause in a reply |
| `sandy_face.c` | LVGL face — 25 moods, blink/drift/doze animations, focus ring, status banner |
| `sandy_status.c` | **the health surface** — see §4.2 |
| `tools/build_feature_matrix.sh` | builds the brain once per enabled `ENABLE_*` flag with that one off; every one must build. A module whose feature is off keeps no-op versions of what other parts call (`sandy_screen.c`, `sandy_led.c`) |
| `sandy_health.c` | the task watchdog (`CONFIG_ESP_TASK_WDT_PANIC`, 10 s): the session manager, `voice_mic`, `voice_feed`, `voice_proc`, `voice_spk`, `voice_tx`, `lvgl`, `mqtt_status` and `app_main` call `health_watch()` and feed it from their loops (the names the watchdog caught are kept in RTC memory and logged once at the next boot, after the network log is up); waits that are long on purpose (socket open and close, a broker publish through a reconnect) sit between `health_unwatch()` and `health_watch()`. **Boot-loop guard:** `health_boot()` runs first in `app_main` and counts crash restarts (panic, watchdog) in RTC memory; `HEALTH_SAFE_AFTER_CRASHES` (3) with no `HEALTH_STABLE_MS` (10 min) run between them boots **safe mode** — Wi-Fi, setup page, remote flash, OTA and MQTT only, no voice, face or body, and MQTT takes only `wifi`, `ota` and `factory_reset`. Status `SAFE_MODE`. A power cut or any normal restart (an update) clears the count. A brownout (the supply sagged) is neutral, the owner's decision: it neither counts nor clears; it is counted on its own in the settings store (`brownouts` ever, `brown_row` in a row, ended by a clean start or a stable run, not by a crash), and `HEALTH_POWER_WEAK_AFTER` (2) in a row is status `POWER_LOW` (part `POWER`, «POWER LOW» on her face), cleared by the stable run. **Memory monitor:** internal RAM under `HEALTH_HEAP_DANGER` free or `HEALTH_BLOCK_DANGER` largest block for a minute, or a `LOW_MEMORY` status standing 30 s, outside a call, ends in `health_restart()` — deferred settings saved first, and counted toward safe mode so a board always short ends there instead of looping. Every other restart saves them first too (an installed update, a rollback, the setup page), except the factory reset, which has just erased them. **Heartbeat:** `health_json()` adds `boot` (last reset reason), `boots` (restarts ever, NVS), `brownouts` (ever, NVS), `power_weak` (`POWER_LOW` stands; the app's robot card says so), `heap_min` (least internal RAM since boot), `heap_big`, `safe`, `nvs_wiped` (the settings store was erased at this boot to recover —
Wi-Fi and the board's keys went with it), `nvs_used`/`nvs_total` (entries in the 20 KB store), `faults` (each part not OK, `{}` when none, so the server's merge clears old ones) and `stacks` (each task's least headroom in bytes); `node_store._TELEMETRY_KEYS` keeps them, the two maps capped at 24 short members. **Stacks:** `CONFIG_COMPILER_STACK_CHECK_MODE_NORM` (compiler canaries) on top of FreeRTOS's end-of-stack canary; the monitor logs once any task under `HEALTH_STACK_EDGE` (512 bytes) of headroom |
| `sandy_mqtt.c` | command subscriptions + status publish |
| `sandy_wifi.c` | association; power save is explicitly **off** (`WIFI_PS_NONE`) for real-time audio, transmit power set to the full 20 dBm |
| `sandy_led.c` `sandy_servo.c` `sandy_buzzer.c` `sandy_motors.c` `sandy_sensor.c` `sandy_touch.c` `sandy_ears.c` `sandy_mic.c` `sandy_spktest.c` `sandy_ota.c` `sandy_nvs.c` `sandy_remote.c` | peripherals, OTA, remote log |
| `sandy_audio_ctl.c` | mic gain/mute, volume; persisted in NVS (noise is the front end's job now) |
| `sandy_echo_probe.c` | dev builds only (`ENABLE_REMOTE`, so never the sale build): on the dev web server, `/echo/arm` records ten seconds of what the front end is fed (both mics and the reference, as it sees them) and what it gives back, from the moment she starts talking, plus each fetched chunk's barge-in inputs; `/echo/status`, `/echo/feed`, `/echo/out`, `/echo/frames` hand it over. `scripts/echo_probe.py <ip>` arms it (`--voice`: from the next near speech, to hear what the uplink makes of the caller; `/echo/wake` opens a call with no wake word), writes four WAVs and reports the echo removed, where the echo sits against the reference, clipping and the barge-ins (§10) |
| `sandy_screen.c` | owner text/picture on the display, Arabic fonts 24/32 |
| `sandy_ir.c` | IR learn + replay (§4.5) |
| `sandy_provision.c` | first-run SoftAP setup (§4.5) |

### 4.1 The session lifecycle

The paid cloud link is open **only** between a wake word and the silence after it.

1. Wake word detected locally (`Hi Andy`) → buzzer cue, `MOOD_CURIOUS`, `s_wake_req`. She
   listens from boot, before Wi-Fi: a wake word with no network gets a sad tone, a worried
   face and `NO_WIFI` on the spot; `app_main` starts the clock once Wi-Fi is up (`clock_poll`).
2. Session manager frees the ~70 KB MultiNet command model **before** opening the
   socket — its internal SRAM is exactly what the TLS task needs. This ordering
   was a real deadlock once; do not reverse it.
3. `ws_open()` → hello → `auth_ok` → `MOOD_FOCUSED`, streaming.
4. Silence for `VOICE_SESSION_IDLE_MS` (8 s) → close, reload the command model,
   back to idle. A `working` frame (a tool running on the server) counts as activity for up to
   `VOICE_WORKING_MAX_MS`.
5. Link lost mid-call → `VOICE_RECONNECT_GRACE_MS` (15 s) of grace before hanging
   up, so a blip does not end a sentence.
6. Two caps the room cannot stretch: `VOICE_SESSION_MAX_MS` (20 min) for any call, and
   `VOICE_NO_REPLY_MS` (90 s) of talk with no audio from her — someone else's
   conversation, not one with her.

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
`LINK_STALL`, `AUTH_FAILED`, `LOW_MEMORY`, `WIFI_BAD_PASS` (a refusal, or a handshake
timeout only when the router is heard at `WIFI_BAD_PASS_MIN_RSSI` or better), `VOICE_OFF` (I2S, the audio
buffers or the front end did not start), `NECK_OFF`, `SCREEN_OFF` (heartbeat and LED only),
`NOT_PAIRED` (part `IDENTITY`: the server opens no call until an account pairs the board; cleared
by the next `auth_ok`), `POWER_LOW` (part `POWER`: brownouts in a row, §4 `sandy_health.c`), `NOT_SET_UP` (part `IDENTITY`: no pairing code or server address, so no call is even
tried — it used to try an empty address and say «no internet»), `SETTINGS_OFF` (the settings store
would not open — she runs on defaults instead of halting; no `ESP_ERROR_CHECK` is left in
an enabled file).

Rules:
- **Subsystems must not set the face directly for error conditions.** Call
  `status_set(part, status)`. Direct face writes are how a half-finished state stayed on screen.
- **Each part owns its status** (`SANDY_PART_SYSTEM`, `_NET`, `_LINK`, `_VOICE`, `_SETTINGS`,
  `_NECK`, `_SCREEN`, `_CLOCK`, `_UPDATE`, `_IDENTITY`, `_POWER`): a part
  recovering clears only its own fault, and she shows the most serious one (`rank` in
  the table). One shared status let a reconnect wipe a memory fault. Wi-Fi clears its
  own part on getting an address; the link on `auth_ok`. The heartbeat lists every part
  not OK (`status_faults_json`).
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

Moved to the per-node namespace 14 Aug 2026 — commit `061cf82`; **nothing global is
left.** The robot is the only board on it: the camera's `cam/` branch and the room node's
`room/` branch went with those boards on 14 Oct 2026.

```
sandy/node/<node_id>/mood · servo · gesture · buzzer · base · led · autonomous · focus · ota
                     · wifi · factory_reset · screen · screen_size · screen_img
sandy/node/<node_id>/mic_l · mic_r                 mute (payload "on" = unmuted)
sandy/node/<node_id>/mic_l_gain · mic_r_gain       digital gain, 0..300
sandy/node/<node_id>/volume · speaker_test
sandy/node/<node_id>/status                        heartbeat → ingest_status
sandy/node/<node_id>/ir · ir/learned               IR learn / replay, captured IR code
```

The server subscribes to exactly `sandy/node/+/status` and `sandy/node/+/ir/learned`, and
`mqtt_ingest._handle_message` reads a heartbeat only from `sandy/node/<id>/status`. A camera
or room board still flashed with the old firmware publishes under `cam/` and `room/`, which
`+` never matches: it is never heard, and its uploads and update checks are refused (§2.9).

`factory_reset` takes only `erase:<unix ms>:<hmac>`, signed by `node_store._erase_command`
with the board's own voice key (the shared key while it has none; both, each in its own message, while its own
key is only issued and may not be saved on the board, `_erase_commands`) over
`factory_reset|<node_id>|<ms>`; the board refuses it unsigned, on a wrong signature, with
its clock unset, or more than five minutes off (`voice_verify_signed`). The own key is loaded at boot (`voice_key_init`, before MQTT), in safe mode too, where the voice task never starts. A bare `erase` on
the broker no longer wipes a robot. A release sends the robot's erase only; the camera's pending
erase rows (`<node_id>:cam` in `node_pending_erase`) left from before are never read and lapse
with the thirty-day TTL.

`wifi` is signed the same way (`wifi_switch._signed_command`, keys from
`node_store.signing_keys`: the board's own, the shared one while it has none, both while its own
is only issued): `wifi:<ms>:<ssid hex>:<sealed hex>:<hmac>`, the HMAC over
`wifi|<signer>|<ms>|<ssid hex>|<sealed hex>` (signer `<node_id>`), and the
password, zero-padded to 64 bytes, XORed with HMAC over `wifi-pass|<signer>|<ms>|0` and `…|1`,
so the broker never carries it. The board refuses it unsigned, with its clock unset, more than
two minutes off, or not newer than the last one it took (a recorded one is never replayed); the
brain checks it in safe mode too, and the setup page is not touched. A brain from before it (under
`0.12.0`, `wifi_switch.SIGNED_FROM`, read from the heartbeat's version) still gets
`<ssid>\n<password>` until it updates; one with no version is sent the signed one. A `board`
other than `brain` (an app from before the camera's removal) is refused, never sent to the brain.

A release keeps its erase (`node_pending_erase`, keyed by board, thirty days TTL): the
broker keeps nothing for a board on a clean session, so a robot off at release used to
keep the seller's Wi-Fi and broker login. Its sealed own key, restart count (`boots`) and
network (`ssid`) at release are kept with it; each heartbeat of the released board sends the
erase again (at most once a minute, signed with its own key and with the shared one, since
it checks with whichever it still has) until it shows the wipe: `boots` lower than at release
(the erase empties the settings store) or another network. Pairing the board again, by
anyone, drops the row first, and the send checks the board is still nobody's: an erase never
reaches a paired robot. `board_wiped` in the release's answer is true only when the erase
went and the board was there to take it; otherwise the app says it erases itself once back.

`node_id` is derived on the board from `SANDY_PAIR_CODE` in `secrets.h` using the
**same transform as `node_store.code_to_node_id`** — lowercase, alphanumerics
only. Keep those two in lockstep; if one drifts the robot goes quiet and nothing
says why. Deriving rather than provisioning means the board knows its own topics
on first boot, before it has ever been paired.

The brain subscribes with a single wildcard one level deep (`sandy/node/<id>/+`) and
dispatches on the suffix, so adding a control cannot be half-done by forgetting a
subscription. One level, not `#`: anything deeper is no command of hers. Every command the brain takes is one level deep; one under a branch would never arrive.
Its own heartbeat still comes back (it is at that level) and is skipped by name.

The heartbeat is retained on the broker, so every server restart is handed each board's
last one again: a retained copy (`msg.retain`) sets `online` but never moves `last_seen`.
The heartbeat carries `capabilities`, `outputs`, `firmware_version`, live per-mic
levels, and the current gain/mute/volume/noise settings. **Those three key names
are the backend's spelling** — `mqtt_ingest` reads them exactly and silently
ignores anything else.

#### One board, its whole outputs

A heartbeat that declares outputs replaces the node's whole list (`node_store._merge_outputs`);
one declaring nothing keeps everything, since silence is not a claim that the hardware is gone.
It used to replace only its own namespace, when the brain, the camera and the room node shared
the id and took turns heartbeating; an output under a branch is now a retired board's
(`retired_output`), dropped from what is kept and refused from what arrives. Telemetry merges by
key and keeps only the keys `_TELEMETRY_KEYS` still knows, so the old `cam_*` and `room_*` go too.

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

**One-shot values are marked** (`meta.momentary`: the melodies, the speaker test, the gestures,
«take a photo», the music's next and previous): the app draws them as buttons that send every tap,
and keeps a picker only for remembered choices (a picker sends only when its value changes).

**The `ir` catalogue row carries no `meta`, deliberately.**
`node_provision._refresh_from_catalogue` merges the catalogue's meta over the
device's on every heartbeat, so a `"buttons": {}` row — even empty — would erase
every button the owner taught, every five seconds, for ever. An absent meta is
how a field is declared to belong to the owner.

"Turn, then fire" needs no new contract: it is a scene — neck angle, then the IR
button.

#### First-run network setup

`main/sandy_provision.c`, added 23 Aug 2026, flag `ENABLE_PROVISION`. When no
network answers within `PROVISION_WINDOW_MS` (90 s) — at boot, or any time the router
refuses the password — or a network that worked has been gone `PROVISION_LOST_MS`
(5 min), the board raises its own
access point — `Sandy-<last four of the pair code>`, WPA2, with a password made at
random each boot — serves a scan-and-pick page on `192.168.4.1`, and shows a QR that
joins it plus the name and password in text on its own screen (never in the log). It is a
captive portal: DHCP names the access point as DNS, a small DNS task answers every A
question with `192.168.4.1`, and any other path (`/generate_204`, `/hotspot-detect.html`)
redirects to the page, so a joining phone opens it by itself. It comes down by itself the
moment the network is back; neither way needs a restart. The scan holds the saved network's
reconnects (`wifi_sandy_hold`) — a connect in progress made it fail — and lists names
strongest first, once each; a field takes a hidden network's name. The page and its answers are in
English and Arabic. The chosen credentials go through `wifi_sandy_switch`, which proves them
before saving and reverts on failure, so a typo cannot leave a board booting onto
a network that does not exist. Proving them is an address within `WIFI_TRY_WINDOW_MS` (25 s)
and then Sandy's server answering through it within `WIFI_REACH_WINDOW_MS` (20 s):
`sandy_reach.c::reach_probe`, `GET /health` over TLS against the server's real certificate
(any status), on a fresh connection; a phone hotspot with no data or a sign-in page fails it
(`WIFI_SWITCH_NO_SERVER`) and the board goes back. The server's `SWITCH_WINDOW_S` (55 s) is
how long the app waits.

On a network that works and reaches nothing, the setup network comes up too: after
`PROVISION_NO_SERVER_MS` (10 min) with no word from the server — the broker connected
(`reach_mark` on connect and every heartbeat while connected), a call's `auth_ok`, an update
check, or a probe — and a probe failing; the station stays on the network meanwhile, the
server is asked once a minute, and its first answer takes the setup network down.

Three things here are load-bearing and easy to undo by accident:

- **APSTA, not AP.** The station side has to stay up to scan and to test. In
  plain AP mode the scan returns nothing and every choice fails invisibly.
- **The page answers before the radio moves.** `wifi_sandy_switch` tears down the
  association the page is served over, so a reply written after it returns never
  reaches the phone and the browser reports failure for a setup that worked.
- **`_retry_task` yields** while `s_switching` or `provision_is_active()`. A blind
  `esp_wifi_connect()` inside a scan or a credential test makes both fail, and it
  reads as a wrong password.
- **The page before the radio.** The owner's build serves LAN flashing on port 80
  (`sandy_remote.c`); the setup page takes the port from it (`remote_http_release`) before
  binding and gives it back once the network returns (`remote_http_resume`). A page that
  still cannot bind leaves the radio alone and is tried again in `PROVISION_RETRY_MS`
  (30 s): it used to raise an access point with no page and no code on her face, and log
  twice a second.
- **Safe mode starts the face for it.** Safe mode boots without the face, and the setup
  network's password is shown only there; `setup_face_on` starts the face the first time the
  setup network comes up in safe mode, and not before.

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
→ `broker_creds.creds_for_device`) and tries it live; it is stored in NVS only once the
broker accepts it and its subscription (`MQTT_EVENT_SUBSCRIBED`, not refused). A refusal of either, or three failed connects (the board's own disconnect that applies it not counted), puts the
old one back (`creds_revert`), so a wrong key can never strand the board. Not over
the broker, deliberately: delivering a broker credential over the broker would
mean the shared login has to keep working for ever, which is the thing being
retired. The voice socket authenticates against a different key, so it still works
after the shared login is revoked — that is what makes revoking it possible.

Only a paired board is handed its row: a board nobody paired reaches the broker with the
shared login its factory partition carries (`scripts/provision_brain.py` writes it, and a
factory reset keeps it), which is what lets a new or wiped robot heartbeat and show its
pairing code before any account is behind it. **That shared factory login must stay on the
broker**, or no new robot can pair. Issuing and revoking are the owner's, by hand on the
broker (the free plan has no API): a release lists the board's login
(`broker_creds.note_released`, `broker_logins_to_revoke`), the owner's `/api/diagnose` shows
the list (accounts in `SANDY_OWNER_ACCOUNTS` only, the app's «why isn't a part showing?»),
and a row leaves it once its login is no longer the one in `SANDY_BROKER_CREDS`.

Issuing is a config table (`SANDY_BROKER_CREDS`) rather
than an API call because programmatic issuing needs the broker's paid plan;
`creds_for_device` is the seam where that swaps in.

The client id is derived from the node id. It was fixed for every brain until
23 Aug 2026 — and a broker allows one connection per id, dropping the older, so
two robots kicked each other off in a loop that never settles regardless of whose
credential each was using. Per-device credentials do not help with that; only the
id does.

**The backend is a broker client too**, and the easy one to forget. `mqtt_ingest`
and `device_publisher` connect with `SANDY_MQTT_USER` / `SANDY_MQTT_PASS`, and unlike a
board the server is not scoped to one node — it listens to every tenant's
heartbeats and publishes to every tenant's devices, so its filter is `sandy/node/#`.
Revoking the shared credential without repointing those two vars cuts the server
off the broker, and the symptom is not an error: heartbeats stop arriving, every
node reads offline, and no device is ever provisioned — because what registers a
device is a heartbeat.

**One topic filter per board.** The free broker plan gives a credential exactly one
permission, which is why nothing global is left: a board's own subtree is all it gets.
Steps to issue the credentials live in `docs/مفاتيح-الوسيط.md` (untracked — `docs/`
is gitignored).

### 4.6 Hardware reality — read before promising a control surface

Updated 14 Oct 2026. **This table is the answer**, and the only other place that
describes the hardware is `firmware/brain-core/HARDWARE.md` — generated by
`scripts/gen_hardware_doc.py` from the firmware itself, with
`tests/test_device_system.py` failing the suite when it drifts. (`docs/HARDWARE_CAPABILITIES.md`
was named here twice and does not exist; the generator has never written it.)

| Part | Reachable from the backend | Physically working |
|---|---|---|
| Face / display | Yes — all 25 moods | Yes |
| Microphones | Yes — per-channel gain, mute, live level | Yes |
| Speaker | Yes — volume 0..100, test tone | Yes, through the voice path |
| Noise suppression | No — inside the esp-sr front end, not a control | Yes |
| On-board LED | Yes — off / idle / listening / talking, plus 11 effects | Yes |
| Neck servo | Yes | **Not physically wired yet** |
| Base motors | Topic exists | `ENABLE_MOTORS = 0` |
| Buzzer | Yes — 17 melodies | Yes — passive piezo on GPIO 17 |
| Distance sensor | No | Dropped; `ENABLE_SENSOR = 0` |
| IR remote | Yes — learn and replay (`ir`, `ir/learned`), in scenes too | Written, not yet tried on hardware |

"Mute the left mic, speak, and watch only the right meter move" now works end to
end — that is the point of per-channel metering, and it is how you tell a dead mic
from a cross-wired one without a multimeter.

**Everything in the first column is true of the source, not of the board on the
desk, until it is flashed.**

The IR code (`main/sandy_ir.c`, on the brain; §4.5) is written and not yet tried on
hardware; `tests/test_ir_scenes_still_work.py` holds its server half. Two-mic separation is
the esp-sr front end's (`sandy_voice.c`, input "MMR").

The camera board and the room node (the light servo and the DFPlayer) were removed on 14 Oct
2026, firmware, server and app; the tag `before-remove-cam-room` holds them. The brain's local
command words that published to the room node (light, fan, music, all off) went with it; the
ones left only open a call.

The Arabic display font is done: `main/fonts/` now carries the typeface at
twenty-four and thirty-two pixels alongside LVGL's built-in sixteen, which is
what makes the text-size control real rather than decorative.

---

## 5. The other boards

There are none. The robot's brain (§4) is the only board; the camera board and the room node
were removed on 14 Oct 2026 (§4.6).

---

## 6. iPhone app

`ios/SandyApp/`, SwiftUI, ~17 400 lines, 14 feature folders. Swift is one module,
so folders are organisation only.

- `App/` — `SandyApp`, `AppState` (holds the base URL), `MainTabView`. **Three tabs**:
  Today, Sandy (the orb in the middle of the tab bar: tap = chat, hold = live call) and
  My Life. Profile opens from the avatar on Today and holds memory (the `fact` log),
  robot, photos, weather settings, persona and account. A tab bar button always shows
  its tab at the root: tapping it with a screen pushed in that tab rebuilds the tab's
  stack (its root's disappearing while the tab is shown marks it as pushed).
- `Features/Today/` — one screen: a sentence about the day, the ask bar (`AskBar`: one
  field for everything, sent to `/api/agent/stream`; Sandy decides what it is and the
  day refreshes; the quick-add shortcut focuses it), the rest of the day as a timeline
  with a live "now" mark (`DayRibbon`), untimed tasks, habits as rings, today's spending,
  focus and home controls. The weather is a read-only corner, like the lock-screen clock.
- **Signing out** (`AppState.signOut`) clears the account's cache files, the widgets,
  Spotlight and the scheduled notifications, and `App/SessionReset.clearShared` wipes
  every shared store that holds the account in memory, so the next account on the phone
  inherits nothing. A new shared store that holds a user's data adds itself there.
  «Reset my data» (Profile › Account) drops the outbox before the server reset (sent
  after it, it would bring rows back), then does the same local clearing still signed in
  (`AppState.resetLocalData`) and builds the main screen again with fresh stores
  (`dataEpoch`); its «done» shows for three seconds at the top of the new one
  (`DesignSystem/NoticeBar.swift`, `NoticeCenter`, which outlives the rebuild and goes with a
  sign-out). A write with no one signed in is refused, never queued.
  `AccountSession.generation` moves on every sign-in and sign-out: a `LoadableStore`
  load that began in an earlier session is dropped when it lands (`isCurrentLoad`), and
  a store made in an earlier session saves and publishes nothing (`inItsSession`: no
  cache file, widget, notification or Spotlight entry for the account that left).
  `NotificationManager` schedules nothing with no one signed in (`sessionBegan` /
  `clearForSignOut`, which also forgets the nudges' task count and habit names). The launch
  (`AppDelegate`) sets it up and marks a kept session, so a banner button or a silent push
  that launches the app with no screen is answered.
- `Core/Networking/` — `APIClient` split into 9 extensions by domain, behind
  `APIClientProtocol`. **Add new endpoints as an extension, not to the base class.**
  Every value put in a URL goes through `URLEscape` (`query` for a parameter, `segment` for a path
  piece), never `.urlQueryAllowed` alone, which lets `&`, `+`, `=` and `/` through.
- `Core/Auth/` — Keychain (`…ThisDeviceOnly`), Google sign-in, auth view. `APIClient` keeps its
  token through a `TokenStore` (the shared Keychain by default) and mirrors its address for the
  extensions only when `mirrorsShared`; tests pass an in-memory store and `false`
  (`SandyAppTests` `TestClient.make()`), so running them never signs the app out.
  `APIClient.session` is a `var` only so tests can answer through `StubNetwork` (no server).
- **Language.** Arabic and English are equal. The app starts in the first of the phone's
  languages it speaks (`AppLang.initial`, else English) and keeps the user's choice
  (`sandy_lang`); every call sends it as `X-Lang`, which the server keeps as the user's
  language (pushes, the daily nudge, limits). Every string the app says itself is in a
  table with both languages; its own errors are `L10nErrors` (`errors.*`), read off the
  main thread with `L10nErrors.s`. The widgets, the share extension and Siri carry their
  own pairs inline (they cannot read the app's tables) and follow `app_lang` in the shared
  group, the phone's before the app has written it (`WidgetLanguage`).
- **Two servers** (`Backend.Server`: production, staging at `Backend.stagingURL`, which
  takes the staging app's Heroku address once it is made). Each keeps its own sign-in: the
  token in use is always in the shared Keychain slot the widget and share extension read
  (`auth.token`, with the mirrored address), and the other server's waits in a slot of its
  own (`auth.token.<server>`, `TokenStore.loadParked` / `saveParked`,
  `APIClient.switchServer`). `AppState.switchServer` refuses while anything is unsent (it
  would reach the wrong server), then does a sign-out's local clearing with the token kept,
  takes the phone's push token off the server it leaves, and opens the other with its own
  sign-in or the sign-in screen. The developer screen (`Features/Developer/`) holds the
  switch (two fixed choices) and the owner's trace and cost pages (`APIClient+Owner`,
  `/api/owner/*`, through `OwnerStore`). It shows in Profile for an account with
  `dev_tools` in `/api/features`' `on` (`ServerFeatures`, `DeveloperAccess`) and always on
  staging, where an orange «تجريبي» badge sits over every screen and opens it, signed in or
  not.
- `Core/Intents/` — App Intents / Siri shortcuts, including device intents.
- `Core/Stores/LoadableStore.swift` — the shared load/error/empty state machine.
- `Features/Blocks/` — **the screens for the blocks (§2.12)**: one generic list screen
  (`ItemsView`, any list in the kinds table; a habit keeps `data.days` (1 = Sunday … 7) and
  `data.time` and shows on Today only on its days, its streak skipping the others; a task
  with `data.repeat` (daily | weekly | monthly) is never closed — `items.update` moves its
  `due` on instead; a task's `data.notes` (where a shared link goes) shows under it, links tappable,
  and is edited in its sheet; habits check in per day as `habit` log
  entries instead of being "done"), one schedules screen (`SchedulesView`, reminders and
  messages to future self) and the log (`LogView`, the My Life tab, with the on-demand
  summary, search, a thirty-day activity strip and a card per list on top). The search's
  server hits live on the store (`LogStore.found`), so an entry found there — older than the
  newest rows the phone holds — is edited and deleted like any other, and the hits follow.
  `KindsStore` loads `/api/kinds` once; My Life builds a card per list from it, so a new
  list needs no app change. **Offline first:** every block change is applied on the
  phone, saved to `DiskCache` and reaches every copy of the same rows (the stores on
  screen, else the file on disk), then goes through `Core/Cache/Outbox.swift`, a
  per-account queue on disk sent in order now, on reconnect, or on return to the front.
  Nothing is queued or sent with no one signed in. A session that ends by itself (a 401) keeps its
  queue on disk (`DiskCache.clearAll(except:)` spares every account's outbox), and it is
  sent only when the same account signs in again; another account never loads it. A
  sign-out the user chooses sends the queue first and, when something is still waiting,
  warns before dropping it (`AppState.sendUnsent`, `Outbox.discard`).
  New rows carry their own 32-hex `id` (the blocks POSTs accept it and a resent POST
  returns the row already there). While the outbox holds anything, a reload keeps the
  phone's copy instead of the server's, and a reload that was already on its way when the
  store's rows changed on the phone is dropped when it lands (`LoadableStore.localEdits`, per
  store, counted from the rows' `didSet`; `applyLoad` puts a load's rows in uncounted). A row
  deleted with «تراجع» still offered stays out of every reload (`UndoCenter.hidden`) until its
  delete is queued. Only a server refusal (a 4xx other than 401, 408
  and 429) undoes a change; a delete answered 404 is done (the row was already gone, deleted
  from chat). A refusal with its caller still waiting is handed to it; one queued earlier
  has no caller left, so it shows a notice and the screens reload the server's copy
  (`sandyBlocksChanged`). A «not now» (5xx, 408, 429) keeps the write first in line: it
  is tried again after a pause that doubles from five seconds to ten minutes, or after the
  429's `Retry-After`; after `Outbox.maxTries` (12) such answers or a day of them it is
  parked beside the queue (`outbox.parked`, on disk, kept by a 401 sign-out like the queue)
  with a notice, so it neither holds the rest up nor is lost, and is queued again when the
  app comes back to the front and before a sign-out, whose warning counts it.
  A chat or ask-bar reply that deleted or changed something (`undo` on the reply,
  `ChatUndo`) offers «تغيّر «…» · تراجع» through the same `UndoCenter` bar for four seconds
  (`ChatStep.offerUndo`); its «تراجع» calls `POST /api/undo` and the tabs reload.
  Done ticks and deletes (lists, reminders, log, conversations) go through
  `Core/Stores/UndoCenter.swift`: one «تراجع» offer at a time; a delete leaves the
  screen at once and reaches the server only when the offer ends (4 s, the next offer,
  or the app leaving the front). A sign-out sends an offer still up first, with the
  session's token, waiting three seconds at most (`commitBeforeSignOut`); one still up
  when the session ends is dropped, never sent as the next account. `DesignSystem/PermissionCard.swift` shows a denied mic
  or notifications where they are needed (ask bar mic, the call, reminders, Profile).
  `DesignSystem/DisplaySettings.swift` holds Profile › Display (text step, element scale,
  light / dark / automatic) and `scaledFont`; every colour token has a light and a dark
  value. `DesignSystem/Accessibility.swift` gives list rows one screen-reader element with
  their gestures as named actions, and `Announce` speaks replies, errors and undo offers;
  every animation goes through `.reduced` (none under Reduce Motion).
  Chat: long-press copy / share / select on any message, «write it again» on Sandy's last
  reply and «edit and resend» on the user's last line (both through
  `POST /api/conversations/<cid>/rewind`, which also takes back what that reply did to
  the blocks, only for the turn of the line it drops: a user line carries the send's
  `client_msg_id` in the conversation and in memory (`stm.rewind` matches it, else the words),
  and nothing in memory is touched when nothing was dropped, so editing a line that failed
  leaves the turn before it alone; it is refused, 409 `turn_running`, while a turn of the same
  user is still running, for two minutes at most (`conversations_api.turn_running`), and the app
  keeps both actions closed from «stop» until the server has the stop, and resends nothing when the
  rewind was refused: every block write in a turn is journaled with its before-state
  (`blocks/_base.journal`, kept on the reply's STM turn as `effects`) and `_base.undo`
  reverses it (a log row it puts back is embedded again, unless sealed); device actions are not undone), a stop button that keeps what arrived, as does opening another conversation or a
  new one while a reply streams (`ChatStore.leave`)
  (`POST …/stop`: a running turn stops before its next tool via `brain/stops.py`, and
  memory keeps only the shown part with a «cut here» note), and a failed line marked
  with «أعد المحاولة», which sends that line again as the same message: its `client_msg_id`
  (kept on the line, `ChatMessage.clientMsgId`), so a turn the server already ran, its reply
  lost on the way, is answered from the ledger and its tools do not run again
  (`conversations_api.claim_turn`, per user and conversation, kept a day), and the line is
  kept once in the conversation (`POST …/messages` ignores a user line whose id is there).
  Attachments (`Features/Sandy/ChatAttachments.swift`): photos, the camera and documents
  upload at once to `POST /api/attachments` (`features/attachments.py`, `sandy_attachments`,
  bytes inline; images 8 MB, documents 5 MB; PDF / Word / text read to at most 20 000
  characters; a Word file whose text part unpacks past 20 MB is refused, `too_big`; a PDF is read page by
  page until there is enough text, at most 300 pages; every attachment, drawn images too, is deleted
  `KEEP_DAYS` (30) after it is saved by a TTL on `expire_at`, rows from before that got thirty days
  from the first boot, `attachments.ensure_expiry`), wait above the field with their progress, and go with the message as ids:
  the turn gives the model the photos as images and the documents as text, memory keeps
  «[صورة: name]». An image Sandy draws is saved the same way and comes back as `image` on
  the reply; the history keeps `attachments` on each message.
  An attachment the server no longer has (404, past its thirty days) shows «الصورة انتهت مدتها»
  (`AttachmentImages.load` → `.expired`) instead of a loading placeholder.
  Loading (`DesignSystem/Loading.swift`): skeleton rows with a shine on first loads,
  `LoadingDots` inside buttons, and `SandyWaiting` (her face and changing lines with the
  user's name) for long waits; nothing moves under Reduce Motion.
  Profile is in four groups (account, app, Sandy and your data, help). Notifications
  (`Features/Profile/SettingsViews.swift`): a switch per kind (reminders, the daily
  nudge, Sandy's proactive nudges) and quiet hours, kept on the phone (`NotificationPrefs`,
  applied by NotificationManager: a kind off is not scheduled, a time inside the quiet
  hours rings silently; pulled on every session start, a change the server has not
  confirmed is kept and sent again rather than overwritten, and sign-out clears them,
  `NotificationPrefs.pull` / `change` / `clear`) and on the server (`GET/POST /api/notification-settings`,
  `features/notify_prefs.py`: the schedule runner and the daily send skip a kind turned
  off and push silently in the quiet hours). **Alarms**: a reminder with
  `payload.important` (Sandy sets it for «صحّيني»/«ضروري»; the reminder sheet has a switch)
  or a task with priority high and a time rings like an alarm: the bundled
  `Resources/Sounds/sandy_alarm.caf` (25 s), and twice more two minutes apart until it is
  answered (a one-off; `NotificationManager.clearAgain`). It keeps to a Focus and the quiet
  hours like any notification, unless that alarm was set to pass them (`payload.break_focus`,
  a switch under «منبه» in the sheet, off by default; then time-sensitive).
  Support sends `POST /api/feedback` with the
  version and device (`sandy_feedback`). The privacy, terms and support-mail values live
  only in `App/AppLinks.swift`, empty until the release.
  Today has a large home-control button, a robot button beside it when a board that
  speaks («audio» capability) is linked, and «أو قولي لساندي شو بدك» under them.
  `Services/Guidance.swift`: one-time TipKit tips (the orb's hold-to-call, row actions,
  the month strip, message actions; at most one a day, gone for good on «فهمت») and
  `ReviewPrompter` (asks for a rating after every fifth finished task, or after a week
  with ten replies; never within ten minutes of an error; at most every 120 days).
  The robot screen (`Features/Sandy/RobotView.swift`) holds everything about her: her
  state now and quick buttons (mood, gestures, melodies, light), the rest of her parts on
  the same screen (`RobotPartsSection`: neck, screen text and image, sound and mics,
  any part the app has no place for), the parts test, her board's Wi-Fi (`NodeWiFiView`, the
  robot only), «why isn't a part showing?»
  (`DiagnoseView`, `GET /api/diagnose` in plain words) and linking/unlinking. Scenes
  (`ScenesSection`, `DeviceScene`) are in home control; the scene editor offers the account's own
  devices and the values each takes. Project lists Sandy made from chat
  («project:<name>») get a card each in My Life.
  Habits: a committed day is one on which every habit due that day was kept; the
  commitment days and the streak (days with nothing due neither count nor break it)
  come from `blocks/habits.py` (up to yesterday, `/api/stats` → `habit_progress`, and
  in Sandy's state block), and the phone adds today when its last habit is ticked.
  A habits store's ticks belong to their day (`ItemsStore.checksDay`, saved with them): past
  midnight or back in front on another day they are cleared and today's are fetched
  (`startNewDayIfNeeded`), and a tap first does the same, so yesterday's check-in is never
  deleted as if it were today's.
  Shopping: when the user says he bought something on the shopping list (any wording),
  the rules tell the model to tick it by id with list_update (or set `qty` to what is
  left), log an expense if a price was said, and never add what is not on the list.
  `undo_last` takes back what the previous reply did (its journaled effects). Live
  voice: an interruption needs pitched sound (`session._voiced`), so noise no longer
  cuts a reply, and a turn opens only on voiced speech (`_ONSET_VOICED_MS`), so a door or
  the TV no longer becomes a question she answers; `gemini-3.8-live` is the first model tried.
  `APIClient+Blocks` is the only client of `/api/entries|items|schedules|kinds|summary`.
  Siri intents, the share extension, the tasks widget's ✓ (`PATCH /api/items/<id>`; a
  `LiveActivityIntent` declared in both targets, so it runs in the app, through the outbox, and
  takes the task's notification away, `CompleteTaskIntent`),
  Spotlight and the reminder banner buttons all write to the blocks. A reminder from Siri is
  sent under the phone's own id and rung on the phone under it (`SchedulesStore.addedElsewhere`). Focus sessions keep
  their own screen (they drive the Live Activity), opened from Today. Their phases advance
  when the session is read (`focus_store._catch_up`, no timer); a session found over more than
  `END_SCENE_LATE` (two minutes) ago is closed without its end scene, so opening the app the
  next day does not switch the room. The Live Activity is read again each time the app comes back
  to the front (`FocusLiveActivity.refresh`), is marked stale at its phase's end, and every change
  of phase to the session's end (`FocusPlan`, from `phase_ends_at_ms`) rings as a local
  notification (`focus.` ids), so a locked phone hears the break, the next round and the end.
- `Services/` — `GeminiLiveManager` (in-app live voice; one shared call that outlives its screen — `CallBar` over the tabs brings it back, the end button, the Live Activity or sign-out end it; a call whose sound does not start is
  ended whole, socket and bar and mic taps, so the next call starts clean; a phone call or Siri
  quiets her and sends nothing until it ends, then the call goes on, or ends with a line when
  its sound cannot come back, `LiveAudio.onLost`; nothing plays on a stopped engine), `SpeechManager` (reply playback only: nothing is read during a live call, whose mic a switch
  to playback would silence, and once read the audio session is given back with
  `notifyOthersOnDeactivation`, so music lowered under the reply comes back up),
  `NotificationManager`, `SubscriptionManager` (RevenueCat configured once, the account switched with
  `logIn` on sign-in and before a purchase or restore, `logOut` on sign-out; the paid features open
  when the server has the purchase, asked a few times while the webhook lands; a failed refresh keeps
  the known status; the store's error shows on the paywall).
- `Localization/` — one `L10n+<Area>.swift` per feature. Arabic/English, RTL/LTR.
  `Localization/Digits.swift` is the one reading of a typed number (Arabic-Indic and Persian
  digits; a comma or ٬ groups thousands; a point or ٫ starts the fraction); every numeric field
  goes through it instead of `Int(…)` / `Double(…)`, which return nil for «٥٠».
- `Widgets/` — home-screen widgets. The app writes the next five reminders' rings to the app group
  (`UpcomingReminders`, a file kept identical in `SandyWidget/`); the widget makes one entry per
  ring, so each shows until its time and then the next, with no app running.

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
  through `scoped()` on `user_id`, and `sandy_changes` (what was deleted or changed, seven days, §2.5).
- **Identity and access** — `sandy_users` (profile, onboarding, persona,
  subscription), `sandy_auth` (login rate limit), `sandy_usage_daily`,
  `sandy_usage_rl`.
- **Conversation** — `sandy_stm`, `sandy_pending_state`, `sandy_prompt_cache`,
  `sandy_cache_stamps`, `conversations` (the app's chat threads, filtered by
  `user_id` by hand in `conversations_api.py`), `agent_turns` (the send ledger,
  keyed by the send's `client_msg_id` within its conversation, TTL a day), `turn_stops` (a stopped reply, `_id` `<user>:<thread>`, TTL a day) and
  `sandy_traces` (one row per turn, thirty days, §2.3).
- **Hardware** — `sandy_devices`, `sandy_nodes`, `sandy_device_keys`,
  `sandy_scenes`, `sandy_voiceprints`, `sandy_voice_enroll`, `sandy_firmware`, `sandy_firmware_chunks`,
  `node_pair_challenges`, `node_sightings`.
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
others — most by `user_id` or `chat_id`, `web_chat_history` and `sandy_voice_enroll` by
`_id`, `turn_stops` by its `<user>:` prefix — so a deleted account leaves nothing behind.
Every collection the code opens is either erased there or named in
`account_delete.NOT_ERASED` with its reason (hardware keys, TTL'd nonces, firmware);
`tests/test_every_collection_is_erased_or_excused.py` reads the code and fails on a
collection that is neither. A partial erase answers 500 `partial` with a
`message`, keeps the account row, and keeps the photo rows when their GridFS bytes
could not go (the rows are the way back to them), so asking again carries on from
what is left; the app shows `account.reset.partial` / `account.delete.partial`.
«Reset my data» (`wipe_account_data`) runs the same erase but keeps the robot and its
devices, the push tokens and the usage counters, and on the `sandy_users` row keeps the
account (`USER_ROW_KEPT`: sign-in, subscription, token generation, zone) while the person
goes (`USER_ROW_FORGOTTEN`: onboarding back to new, persona, budget, city, notification
settings). Every field the code writes to that row is in one of the two;
`tests/test_reset_keeps_the_account.py` fails on one that is not.

Indexes are created at boot on the raw handle — by each store's `init_*` and
`init_blocks`, and by `bootstrap.ensure_indexes()` for the rest (pending state,
prompt cache, pairing TTLs, conversations, focus, and one active focus session
per user, `focus_store.ensure_one_active`, which first closes the extra ones, the newest kept) — one `try` per
index, so one failure cannot skip the rest. `sandy_stm`'s three are created on
first use by `brain/stm.py::_ensure_stm_indexes`, same one-try-each rule, and
retried until they exist: `(user_id, updated_at desc)` is what keeps the
cross-channel read from scanning every conversation on the server.

---

## 9. Tests and CI

141 test files, pytest + mongomock, no hardware and no live credentials needed.
`tests/test_device_system.py` carries the headline guarantee: the brain may only
act on a **registered** device with a **validated** action, and refuses with the
allowed list rather than guessing. `tests/test_routes_kept.py` pins every route a
client calls; `tests/test_tenant_isolation.py` runs every store through the
isolation contract; the `test_brain_*` files drive the loop with a scripted model.

**The real model is scored apart from the tests** (`scripts/eval_brain.py`, cases in
`scripts/eval_cases.py`): real sentences through `loop.run_turn` on the real chat
deployment (`--model` picks another), on an in-memory database, with the outside tools
(devices, scenes, search, weather, images) as recording stand-ins. Each case checks what
was done (tools called, rows left behind, a held yes), not the wording, and the run
prints a pass rate, the seconds per message and what the run cost (tokens and dollars from
the turn traces, `features/pricing.py`). A step may also check a tool's arguments (`args`:
one call of that tool carries the values; a word of text is found inside the call's text).
`--repeat N` runs every case N times and names those whose outcome differed; `--save` writes
`scripts/eval_results/<when>.json`, the first saved becomes `baseline.json`, and every later
saved run says what fell and rose against it. More than five percent of the cases moved
(`ALLOWED_SHARE`; two cases until 29 Oct), between repeats or against the baseline, fails the
run, as do a language under ninety percent (`PASS_SHARE`) and English more than `LANGUAGE_GAP`
points behind Arabic (`_verdict`); nothing else does: a case that fell on its own, or got no
answer, is printed as a warning. `--temperature` runs the brain at another `model.TEMPERATURE`. Imported (by `tests/test_eval_report.py`) it reads no
command line and no `.env`. It costs model calls, so it runs by hand before a model or
prompt change, never in CI. First run on `gpt-4.1` (4 Oct 2026): 31/34;
the misses were «خلص الحليب» and «لازم أخلص التقرير» answered without adding, and
«ذكريني كل يوم» made a habit instead of a reminder. Baseline of 28 Oct 2026
(`eval_results/baseline.json`, forty cases): 36/40 on the `sandy-chat` deployment, which is
`gpt-4o-mini`; the run after it moved five cases (delete one item answered with
`list_update`, «جهزي الغرفة» with `room_restore`, and three that rose), so two runs still
differed by more than the two cases then allowed. After the delete and scene rules (29 Oct, forty-two
cases): `sandy-chat` 38/42 then 41/42, three cases apart, about $0.044 a run and 1.9 s a
message; the `gpt-4.1` deployment (`--model gpt-4.1`) 40/42 once, about $0.52 a run and
3.2 s a message. Since 29 Oct every Arabic case has an English sister (`<name> · en`,
`EN_CASES`) with the same checks and its reply checked to be English (no Arabic word but a
«quoted» name or a device label); each language is scored on its own and English may not
trail Arabic by more than `LANGUAGE_GAP` (5) points. Baseline: ar 40/41, en 40/42. After the independent review's fixes (29 Oct, `eval_results/2026-10-29T1142.json`,
two runs at temperature 0.5): ar 41/41, en 41/42, one case of 83 moved (1.2%), about $0.19
for both. At 0.2 the score was no better (79/83, three moved), so 0.5 stays. After the second
review's ten fixes (29 Oct, `eval_results/2026-10-29T1409.json`, one run): ar 40/41, en 41/42,
about $0.09; against the baseline «bulk delete asks then goes» fell, «fact» and «weather · en» rose.

The app's unit tests run from the terminal with `scripts/run_ios_tests.sh`, which keeps every
run's log, result bundle and failed tests by name in `ios/test-results/` (not in git). The test
bundle's principal class (`SandyAppTests/TestRun.swift`, `INFOPLIST_KEY_NSPrincipalClass`)
removes the cache folders of the accounts the tests made once the run ends.

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

**Echo cancelling on the robot:** with the dev firmware on the LAN,
`~/sandy_app_venv/bin/python scripts/echo_probe.py <board ip>` arms the probe, waits for her
to talk, and reports what the front end did with her own voice. Measure before touching the
barge-in thresholds: on 9 Oct 2026 the reference wandered up to 300 ms behind the echo and the
cancelling added 8 dB instead of removing any.

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
   with it (`"kv": 2`) and the shared key is refused for that board.
   Un-pairing revokes it (`key_unknown`). What is left: inside
   the window, someone holding the shared key who connects as that board first
   gets its key (the real board is then refused — visible, not silent).
   Closing it fully means writing each board's key at flash time.
0b. **Firmware updates.** Since 19 Sep 2026 the brain pulls signed releases
   (`sandy_ota.c`, `features/firmware_store`, `api/firmware_api`): a manifest
   signed with the owner's ECDSA P-256 key (`scripts/firmware_keygen.py`;
   private key off-repo and off iCloud, encrypted, at `~/.sandy-signing/firmware-signing-key.pem`
   with the publish token beside it; the script asks the key's password; public key in `main/fw_pubkey.pem`), streamed into the
   idle slot with the size and SHA-256 checked before switching, canary ids
   then a stable percentage (`scripts/publish_firmware.py`; a board is offered the newest release
   it is in the rollout of, so a canary held at 0 % never hides the stable one; releases older than
   the newest one out to everyone are deleted with their chunks, `firmware_store._prune`), never a downgrade,
   bootloader rollback if the new image cannot reach Wi-Fi or, within thirteen minutes, the update
   server (`_health_task`; time a call holds the network is not counted, and nothing rolls back
   while a call is on). The version is noted as `trying` before
   the boot slot is switched and stays noted until that image is confirmed (`ota_confirmed`), so an
   old image the bootloader came back to finds it, counts the failed trial and, after
   `OTA_BAD_MAX_TRIES` (2), is not offered it again. A failed check, download or
   install comes back in five minutes, doubling to an hour (`OTA_FAIL_RETRY_MAX_MS`), not
   after the six-hour period; nothing downloads under `OTA_MIN_RSSI` (-80 dBm), and from
   the download to the restart her face says `UPDATING - DO NOT UNPLUG` (status
   `UPDATING`, part `UPDATE`, above every fault). The MQTT `ota`
   command only triggers a check — it no longer takes a URL. Published images
   are always the sale build (`idf.py -B build-retail -DSANDY_RETAIL=1`), which
   compiles `ENABLE_REMOTE` (LAN upload + log on 3333) out; the publish script
   refuses an image that still contains it (`brain_image_refused`: the log task, the upload
   task or its page), one whose version string is not this source's (a stale build-retail
   would install and be offered again for ever), or one carrying a value from the real
   `secrets.h`; `--check` runs the refusals without a key or an upload. Still open: secure boot and flash encryption are off.
1. **Sentry is wired but only as good as its DSN.** `integrations/error_tracking`
   starts at boot when `SENTRY_DSN` is set; `before_send` strips request
   bodies and query strings and, since 19 Sep 2026, log breadcrumbs down to their
   `[tag]`. Frame variables are off at the source (`include_local_variables=False`)
   and stripped again if any arrive, and performance traces pass the same scrubber
   (`before_send_transaction`).
   Without the DSN, failures are still discovered by the owner using the
   product.
2. **The robot's body no longer reacts to what she does.** The celebrate /
   acknowledge / focus melodies and faces were called only by the old goal,
   task, habit and focus tools; the brain never called them, and phase 5 deleted
   the unused `robot_expression` module. The board side (gestures, melodies,
   light effects) is intact; wiring it back means the brain's `list_update`
   (done) and the focus routes calling one small helper.
3. **A POST is never retried, and the chat send is a POST.** `sendWithRetry`
   guards on GET/HEAD because retrying a write could duplicate it, which is
   right — but it means the one dropped packet that motivated the whole change
   is still a red banner on the most-used call in the app. An idempotency key
   on the send is what would close it.
4. **A tool call costs two model calls in series** — the one that picks the tool
   and the one that writes the answer; plain conversation is one. The fast path
   answers a bare device command with none, and a turn of answer tools only
   (§2.3) skips the second call. `[turn] …ms total — brain tools=[…]`
   (§2.11) gives the time per message.

9. **The chat model runs out under load, and its fallback has no credit.** On 28 Oct 2026
   the `sandy-chat` deployment (`gpt-4o-mini`, Azure Spain Central) answered 429 «exceeded
   token rate limit» at about 240 000 tokens a minute, and OpenAI direct, the fallback,
   answered 429 «no credits remaining». The user sees `loop.ERROR_REPLY`. The fix is a
   higher token quota on the deployment, or credit on the fallback.
   The deployment itself retires on 14 Apr 2027: the chat must move to another model,
   measured with the eval, well before then, and to Azure's `/v1/responses` with it:
   `gpt-6-luna` refuses reasoning with tools on `/v1/chat/completions`. Its price in
   `pricing.py` is from an outside page (`pricing.UNCONFIRMED`), to check on the first bill;
   a cost counted from it is a warning in the log, once a process.

10. **A streamed reply in the wrong language shows, then is swapped.** The model's words
   stream as they come; the language check (§2.3 3c) runs after, and the final event
   replaces the text. Low: the right reply lands, but the wrong one is seen first. Later.

### Real, but nobody hits it today

5. **Staging: built, not yet created.** The code side is in (§1, `env_guard`); the owner
   creates the Heroku app from `docs/STAGING.md`.
6. **`GeminiLiveManager`'s own `URLSession`: fixed.** The call's socket now comes
   from the app's shared `APIClient.session`. (A scene was also sent twice per apply —
   once by `apply_scene`, again by its callers; `apply_scene` alone sends it now.)

7. **Related-memory recall: fixed.** `context.similar_entries` now asks the
   Atlas vector index `entries_vector` (on `sandy_entries.embedding`, filter fields
   `user_id` and `kind`) through `ScopedCollection.vector_search`, which puts the
   tenant in the `$vectorSearch` filter. The index lives in Atlas, but its definition
   lives in `blocks/vector_index.py` (1536 dims, cosine, filters `user_id` and `kind`):
   every boot runs `vector_index.ensure` once on the shared pool, which makes it when
   it is missing and leaves one that is there alone; a failure is a warning and boot
   carries on. `scripts/ensure_vector_index.py` does the same by hand. A missing index
   makes `$vectorSearch` return nothing, not an error, so an empty answer is checked
   (`vector_index.not_ready_reason`, once per process when ready) and a missing or
   still-building index is logged by name before the word search. Encrypted rows (moods,
   facts) are never embedded, so they are never found this way.
8. **`submit_background`'s ten workers carry two model calls per turn** (the STM
   summary and the conversation title) with no future ever read. Both go through
   `chat_fn` with `OPENAI_CHAT_TIMEOUT_S`, so a stalled upstream costs a worker
   for that long, not for ever. A sizing question, wanting a measurement first.
### Hardware, and the owner already knows

9. **Voice status clips are not flashed** — the sentences are in the table, the
   speaking hook is not written and the partition table has no room reserved. §4.2.

### Checked and closed since the last version of this list

The firmware **is** built in CI (`idf.py build`, §9), so "never compiled" is no
longer true. The control page **exists** (`ios/SandyApp/Features/Control/`). Nothing
global is left on the broker (§4.5), and nothing is owner-only on the way to a device. The display **has** an Arabic font at 24 and 32 pixels
(`firmware/brain-core/main/fonts/`). `feature_flags.py` (unused) was removed. Servo easing and ten gestures are in
(`sandy_servo.c`). The visitor approval flow and the JSON profile store are gone.
The brain **is** told which devices exist: `context.devices_line` lists them by name and room in the chat prompt and in the call's per-session context (`voice_ws/memory.session_context`, uncached). Phase 5 closed three more by deleting what they were about: `tool_health` (no
tool registry left), the 28-round-trip warm turn (the persona-directive build
and the old memory layers are gone), and the router-then-reply pair on every
message (plain chat is one call). Since then: the voiceprint has a client (Robot ›
«صوتي», §3.2), and two-mic separation is the esp-sr front end's (§4).
