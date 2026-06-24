# Sandy — Product Migration Plan (clean multi-tenant)

> Bootstrap doc for a fresh Claude Code session in this repo. Read this first.
> Chat with the owner is in Arabic; this doc is English (repo convention).
>
> For the product "why and what" (robot + app + learnable physical extensions,
> sold to companies and homes), see `PRODUCT_VISION.md`. This doc is the "how" of
> the backend migration that makes that vision possible.

## ⭐ TOP PRIORITY (do this first)

**Ignore everything old. The #1 move is to stand up the clean product backend and
deploy it to Heroku FAST — ahead of polishing the owner-centric app.** The personal
single-user setup (old Heroku apps, Telegram, owner special-casing) is legacy; do
not invest more in it. Get the new multi-tenant API live, then build outward.

Order of attack: **Phase 1 (product DB) → Phase 2 (kill Telegram) → Phase 3 (enforce
tenant / de-owner) → deploy the new backend to Heroku.** Frontends and feature
parity come after the new backend is live and clean.

> ✅ **DONE (2026-06-25): the clean backend is LIVE.** Phases 1–3b finished, the
> Phase 1 migration was run, and the clean product backend is deployed to Heroku
> (it took over the old `sandy-robot` app, now serving DB `sandy-app` via
> `gunicorn`). The web frontend moved to GitHub Pages (free) and the iOS app
> points at the live backend — both verified end-to-end (owner login → real data).
> The remaining work is feature parity (port the web-only tools to iOS) and the
> deeper isolation polish (Phase 4: per-tenant facts/persona/memory).

## 1. What we decided (the vision)

Sandy is becoming a **public, paid, multi-user product** — NOT the owner's personal
single-user assistant with users bolted on. The headline principle the owner
stressed hard:

> **Everything is isolated per user — robot, personality, memory, room, all of it.
> The owner (Nabeel) is a distinct, privileged account, fully separate from every
> other user. "I'm different from everyone."**

Locked product decisions:

- **One clean backend, many frontends.** A single well-organized API serves
  iOS (built), Web, Android, Mac, Windows. Frontends differ; the brain is one.
- **Telegram is removed entirely.** The owner stops using Telegram and relies on
  the app. No Telegram code in the product. (The original `/Desktop/Sandy` repo
  stays as a dormant personal archive — do not touch it for product work.)
- **Clean separate product** (chosen over "keep one shared brain"): the product
  gets its **own database and codebase**; the owner becomes **tenant #1** with his
  data migrated in. His robot/room become **his tenant's integrations**, not
  global code. The Telegram/robot channels become channels of his tenant.
- **Isolation by architecture, not by `if`.** Every user — including the owner — is
  a tenant. A tenant id is required at the data layer (fail-closed). Nothing is
  global: not facts, not persona, not robot. This is the core fix; today's
  isolation is filter-based and leaks (see below).
- **Per-user personalities that evolve.** Each user starts with a pleasant, generic
  persona that **personalizes with use (Gemini-style)** via a per-tenant learning
  layer. The owner keeps his own distinct persona.
- **Progressive onboarding, not interrogation.** Do NOT bombard questions on first
  open (that produced an annoying onboarding screen). Instead, broaden the profile
  gradually via **gentle in-app notification nudges** ("want me to understand you
  better? take this short survey") — professionally, over time.
- **Robot/room are per-tenant device controls, not owner-only** (refined
  2026-06-22). The owner controls HIS `room-node` over MQTT because he owns that
  hardware — but any tenant who owns devices/extensions gets the same controls for
  THEIR hardware. Nobody actuates another tenant's hardware. The owner is not a
  special case here; he just happens to have devices today.

## 2. Current reality (codebase grounding)

The good news: the foundation is decent — this is **consolidation + cleanup, not a
rewrite.** A prior multi-user pass landed (~6 commits; user-vs-user isolation was
verified). What exists today in `cloud/`:

- **Tenant context already exists.** Requests wrap work in
  `active_user_profile_context(build_user_profile(claims))`; stores read the active
  tenant via `current_user_id()`. ~20 files use this scoping. It just isn't
  *enforced* (fail-open) and is surrounded by owner branches.
- **Shared DB.** `MONGODB_DB_NAME` defaults to `sany-db` (config.py) — the SAME
  database as the owner's personal Telegram/web Sandy. The product currently runs
  on the owner's personal data. This is the entanglement to break.
- **Owner special-casing spread across ~18 files** (`SANDY_USER_CHAT_ID`,
  `is_owner`, `role == "owner"`, `_is_guest`). Owner is hardcoded id `628544372`.
- **Two real "global" leaks:**
  - **Facts:** `semantic_memory.search_relevant_facts(query, n_results)` takes NO
    tenant — semantic facts are searched globally (cross-user leak).
  - **Persona:** `SANDY_PERSONALITY` is one global env var for everyone.
- **life/productivity APIs are still owner-only** (non-owners get demo data); only
  `/api/agent` is truly multi-user. Needs unifying.
- **Telegram still present:** `app/api/telegram_handlers.py`, bot registration,
  `/webhook` routes, `pyTelegramBotAPI` dependency.

## 3. Target architecture

- One multi-tenant backend. **`tenant_id` mandatory on every document and every
  query, enforced by a single data-access layer that fails closed** if no tenant is
  set. No store can read/write unscoped.
- **Owner is a normal user — NO in-app privilege** (decided 2026-06-22). He is
  just tenant #1; same persona/tools/integrations as everyone, nothing more. Ops
  and monitoring (Heroku, etc.) the owner does OUTSIDE the app, not as an in-app
  role. So Phase 3 deletes the owner special-casing outright (no `admin` flag to
  add) and the in-app ops/admin tools that were owner-gated go away.
- **Per-tenant config** replaces globals: persona (evolving), integrations
  (robot/room/extension topics), preferences — all stored on the tenant. Device
  controls (robot/room/extensions) show for ANY tenant that owns devices, not the
  owner specifically.
- Frontends are thin clients over the same API (iOS done; Web = reuse `sandy-web`
  repointed; Android/Mac/Windows later).

## 4. Migration phases (ordered)

**Phase 0 — Setup.** Work stays in `Sandy-App` (already a separate repo). Snapshot
/ branch before structural changes.

**Phase 1 — Product DB + migrate owner as tenant #1.** New `MONGODB_DB_NAME`
(e.g. `sandy-app`). Migration script moves the owner's data (currently tagged with
his id, plus any legacy `user_id=None`) into a clean tenant id across all stores:
tasks, reminders, habits, expenses, scenes, summaries, facts, journal, onboarding.
  - DONE (script written, not yet run): `cloud/migrations/001_migrate_owner_to_product_tenant.py`.
    Owner-approved decisions (2026-06-22): clean owner id = his `sandy_users`
    account uuid (unifies auth + data); migrate everything incl. legacy untagged.
    Copy-only, idempotent, dry-run by default (`--apply` to write). The run prints
    the owner tenant id to wire into `/api/auth` in Phase 3. Owner runs it.

**Phase 2 — Remove Telegram completely.** Delete `telegram_handlers.py`, bot
registration, Telegram `/webhook` routes, `pyTelegramBotAPI` from requirements, and
every Telegram branch. Clean deletion — no dead/unused code left behind.
  Owner extended the scope (2026-06-22): also remove ALL social-media posting
  (Telegram + Instagram + Facebook + LinkedIn), not just Telegram.

  DONE (2026-06-22) — verified: server boots, `/health` ok, `/api/agent` wired
  (401), old `/webhook` gone (404), `ruff` clean, no `import telebot` anywhere.
  - Social-media posting removed (Telegram/Instagram/Facebook/LinkedIn): deleted
    `integrations/social_*.py` + `agent/tools/schemas/social_*_tools.py`, unwired
    from `agent/tools/setup.py`.
  - Owner Telegram alerts removed: deleted `integrations/owner_notify.py`, dropped
    the `notify` path from `incident_tracker.maybe_escalate`.
  - App factory extracted: `api/webhook.py` → `api/server.py` with `create_app()`
    (no Telegram). `serve_api.py` now builds the app directly; the misnamed
    `telegram_webhook_runtime` wrapper is gone.
  - Deleted Telegram-only files: `api/telegram_handlers.py`, `api/telegram_runtime.py`,
    `api/telegram_guards.py`, `integrations/telegram_api.py`, `sandy_agent.py`, and
    the now-dead Telegram-only `features/voice.py`. Removed the bot/scheduler/`main`
    wiring from `agent/facade/agent.py` (it now just wires clients + stores + the
    shared `agent`).
  - Unthreaded `telegram_bot`/`telebot.types` from the agent pipeline (nodes
    execute/pending, executor dispatch/task_handlers/email_pending, guest_usage).
    The per-turn `reply_markup` is now always `None`; the app renders its own
    confirm UI from `pending_state`.
  - Removed `pyTelegramBotAPI` from requirements, Telegram vars from `config.py`
    (`TELEGRAM_BOT_TOKEN/SECRET`, `RUN_MODE`, `SANDY_COMMAND_MODE`), and the
    `telebot` logger entry from `bootstrap.py`.

  Deferred (intentionally, not dead-Telegram-code):
  - Proactive delivery functions (`reminders_store.check_due_reminders`,
    `email_watch.check_new_important_emails`, scene firing) are delivery-agnostic
    (take a `send_message_fn`) and currently unwired — they get re-wired to in-app
    push in Phase 7, so they were left in place (and `apscheduler` kept for that).
  - `SANDY_USER_CHAT_ID`/`OWNER_CHAT_ID` kept — owner identity, folded into a
    tenant role in Phase 3.
  - The legacy guest access-request approval (and `guest_usage.approve/reject`)
    lost its Telegram trigger; `_notify_owner` is now a documented no-op pending
    the Phase 7 push/admin path.

**Phase 3 — Enforce tenant (fail-closed) + de-owner.** Any data access without a
tenant is rejected. DELETE the ~18 owner branches (no `admin` flag replaces them —
owner is a normal user, decided 2026-06-22). Remove in-app ops/admin tools that
were owner-gated (owner runs ops outside the app). Owner stops being a special
code path entirely.

  Mapping + decisions (2026-06-22), ordered for implementation:
  1. REMOVE the in-app email/Gmail feature entirely (owner decision) — it is a
     single shared Gmail account; opening it to all users would leak the owner's
     mail, and per-user Gmail OAuth is a later feature. Delete `features/gmail.py`,
     `features/email_watch.py`, `api/emails_api.py`,
     `agent/tools/schemas/email_tools.py`, `agent/email_resolve.py`,
     `agent/executor/pending/email_pending.py`, and unwire from `tools/setup.py`,
     `api/server.py` (register_emails_api), `studio_api.py`, `facade/briefing.py`,
     executor `dispatch.py` + `pending/dispatch.py`. (Same shape as the social
     removal: a clean feature deletion.)
     DONE (2026-06-23) — boot-tested: `/health` 200, `/api/emails` now 404, ruff
     clean. Also deleted the Gmail-only OAuth helpers (`integrations/google_oauth_env.py`,
     `utils/google_oauth_errors.py`), dropped the dead `GoogleOAuthReconnectNeeded`
     path + unread-inbox block from `facade/briefing.py`, removed `gmail_list_state`
     from the graph state + `email_send_draft` from `memory.py`/`deep_context.py`,
     swept every email example/template out of `fc_router.py`, `model_fallback.py`,
     `response_templates.py`, `shadow_execution.py`, `voice_ws.py`,
     `self_awareness_tools.py`, and dropped `google-api-python-client` +
     `google-auth-oauthlib` from requirements.
  2. REMOVE in-app ops/admin agent tools (owner does ops outside): GitHub
     (`integrations/github_api.py`, `heroku_tool.py`, incident/deploy tooling) and
     their tool schemas — wherever they were owner-gated.
     DONE (2026-06-23) — boot-tested: `/api/github/issues` + `/webhook/sentry` now
     404, 78 tools registered with zero leftover ops tools, dispatcher builds.
     Deleted `integrations/github_api.py`, `tools/heroku_tool.py`,
     `tools/cost_tool.py`, `agent/incident_tracker.py`. Removed the GitHub tools
     (commits/issues/create/close/reopen/comment/file/changelog) from
     `schemas/mcp_tools.py` (now memory+fetch only) and `cost_report`/`github_info`/
     `heroku_info` from `schemas/other_tools.py`; dropped the `heroku`/`cost`
     dispatch handlers. Removed the now-dead `_is_owner_only_tool` filter from
     `graph/graph.py` and the github_/heroku_/cost_ owner prefixes from
     `nodes/execute.py`. Deleted the now-orphan MCP hub: `integrations/mcp_client.py`
     + `register_mcp`/`tool_type`/`mcp_server` plumbing in `tools/registry.py` +
     `tools/dispatcher.py` (GitHub was its only consumer). Removed the Sentry
     incident webhook from `api/server.py`, the `/api/github/issues` route from
     `studio_api.py`, github sensitive-tools from `voice_ws.py`, and `GITHUB_*`
     from `config.py`.
  3. DE-HARDCODE the owner: drop the `628544372`/`SANDY_USER_CHAT_ID` fallback and
     the `is_owner`/`role=="owner"`/`active_profile_allows_privileged_access`
     branches that gate *a user's own data*. Every authenticated user gets full
     CRUD on THEIR data (productivity_api already does this via guest-vs-user).
     DONE (2026-06-23) — boot-tested. Root fix in `utils/user_profiles.py`:
     `build_user_profile` now gives EVERY authenticated caller (owner + user)
     `permissions="all"` and `relation="user"` (no owner branch, no owner-id
     fallback — a token without `user_id` yields an empty scope). Deleted
     `active_profile_is_owner` + `active_profile_allows_privileged_access`;
     rewrote `active_profile_is_guest()` to test `permissions != "all"`. Agent
     gates now block GUESTS, not non-owners: `task_handlers`, `reminder_handlers`,
     and the `nodes/execute.py` tool gate (split into `_requires_account` →
     guest-blocked secretary tools, and `_OWNER_DEVICE_PREFIXES`/`hardware_` →
     owner device, transitional). `api/server.py` flipped every `role=="owner"`
     vs-rest check to guest-vs-authenticated (chat-history key/expiry, image +
     analyze + guest-usage limits) and dropped the owner-id fallback; owner now
     shares the top (subscriber) usage tier instead of being unmetered.
     `studio_api.py` de-ownered (per-user plans/search, brainstorm queries scoped
     by the caller's id — closed an unscoped global brainstorm search). `auth_handlers`
     token lifetime is now authenticated-vs-guest; deleted the dead `require_owner`.
     KEPT (transitional, owner identity not privilege): owner password login +
     `SANDY_USER_CHAT_ID`/`OWNER_CHAT_ID` (his current tenant id until the Phase 1
     migration is run and the clean id is wired), `users_store.get_or_create_owner`,
     and `semantic_memory` legacy-doc tagging (assigns pre-isolation docs to the
     owner = tenant #1).
     DEFERRED to Phase 4/5 (would otherwise LEAK): `agent/memory.py` is the legacy
     GLOBAL memory/session (`sandy_memory`/`current_session`, one doc for everyone)
     — kept owner-scoped via `is_owner_chat_id(current_user_id())` so other users
     can't read/write his global state; Phase 4 makes it per-tenant. `api/voice_ws.py`
     stays owner-only (owner token + owner STM + CAM++ speaker-id); opening it
     needs per-user voice wiring (Phase 5/6), else it would serve the owner's STM
     to others.
  4. ENFORCE fail-closed: stores refuse a read/write when `current_user_id()` is
     None (the security core). DONE/VERIFIED (2026-06-23) — the prior multi-user
     pass already added `uid = current_user_id(); if uid is None: return []/{}`
     to every feature store (tasks, reminders, habits, expenses, scenes, journal,
     reading, shopping, focus) and every query filters by `{"user_id": uid}`.
     Audited all mongo ops across the nine stores: no unscoped read/write remains.
     Smoke-tested: with no active profile, `load_tasks()` returns `[]` and
     `current_user_id()` is None. (Global facts/persona are the remaining globals —
     Phase 4.)
  KEEP (do NOT remove): the guest-vs-authenticated gating (`_is_guest`, demo
  payloads for visitors) — that is visitor limiting, not owner privilege. Robot/
  room stay the owner's device controls transitionally (his only hardware), per
  the per-tenant device-controls model above.

  ALL FOUR STEPS DONE (2026-06-23), boot-tested + ruff-clean. Phase 3 complete.
  Carried into Phase 4: make `agent/memory.py` (global `sandy_memory`/
  `current_session`) per-tenant, and `search_relevant_facts` + persona per-tenant.
  Carried into Phase 5/6: per-user voice (`api/voice_ws.py` is owner-only today).

  **Phase 3b — Isolation by construction (2026-06-24).** The fail-closed scoping
  above was still per-query (`{"user_id": uid}` hand-written in every function) —
  fragile: one forgotten filter is a cross-tenant leak. That class of bug actually
  shipped (any authenticated user could drive the owner's room scenes). Two root
  fixes landed so it can't recur:
    1. **Enforced data layer** `cloud/app/utils/tenant_db.py` — `ScopedCollection`
       + `scoped(db, name)`. It stamps `user_id` onto every find/insert/update/
       delete/aggregate automatically and returns `None` when there's no tenant, so
       each store's existing `if coll is None` guard now fails closed on "no tenant"
       too. The 8 data stores (tasks, shopping, reminders, habits, journal,
       expenses, focus, reading, scene) were converted to it; manual `user_id`
       injection removed. Two deliberate exceptions keep an explicit-tenant raw
       path (no thread-local profile): the reminder minute-poller and `usage_store`
       rate-limiter, both scoped by an id passed in / embedded in `_id`.
    2. **Device boundary gate** `integrations/room_device.py` — owner-ownership is
       checked INSIDE `send()`/`apply_actions()`, not at call sites, so no path can
       actuate the room without being the owner (transitional until per-tenant
       device ownership in Phase 5).
    3. **Automated isolation test** `tests/test_tenant_isolation.py` — for every
       store + the memory tool: tenant A's data is invisible to B, B can't mutate
       A by id, and every op fails closed with no tenant. The regression net that
       turns this bug class into a red CI run instead of a production leak. Also
       fixed the stale `tests/conftest.py` import of the Phase-2-deleted
       `mcp_client`. (Pre-existing Phase-2 orphan tests that import removed modules
       — voice/webhook/heroku/telegram — still error on collection; separate cleanup.)

**Phase 4 — Close the globals.** `search_relevant_facts` becomes per-tenant.
Persona becomes a per-tenant field (starts pleasant, evolves with use). Also make
`agent/memory.py` (`sandy_memory`/`current_session`) per-tenant — it is the last
shared global, kept owner-scoped transitionally at the end of Phase 3.

**Phase 5 — Unify routes.** life/productivity APIs serve any tenant (no owner-only,
no demo payloads). Robot/room actuation gated to the owner tenant only.

**Phase 6 — Frontends.** One backend serving iOS + Web → then Android / Mac / Windows.
  DONE (2026-06-25):
  - **Backend deployed to Heroku** — the clean `Sandy-App` repo (GitHub:
    `AlsultanNabeel/sandy-backend`) now runs on the existing `sandy-robot` Heroku
    app (so the URL `sandy-robot-3da0693d32f7.herokuapp.com` is unchanged for the
    clients). Served by `gunicorn` (concurrent) instead of the werkzeug dev server;
    a single werkzeug worker was dropping bursty pull-to-refresh calls (Heroku
    H27). Entry point: `cloud/wsgi.py`. Python pinned to `3.11` (`.python-version`).
  - **Web → GitHub Pages** (free): `sandy-web` now builds + deploys via a GitHub
    Actions workflow to `alsultannabeel.github.io/sandy-web`; the old web Heroku
    dyno was deleted (freed a slot + saved money). `FRONTEND_URL` Config Var set to
    the Pages origin so CORS allows it.
  - **iOS pointed at the live backend** (`AppState.swift` baseURL). Verified: owner
    login returns the clean tenant id, real data shows.
  - **iOS data layer rebuilt to per-feature stores** (single source of truth):
    `TasksStore / RemindersStore / HabitsStore / ExpensesStore / JournalStore /
    HomeStore`. The fetch runs in a store-owned `Task`, so a pull-to-refresh or tab
    switch that ends the view gesture no longer cancels it (new data always lands).
    Home additionally keeps last-good data on a transient/failed snapshot
    (stale-while-revalidate) so the dashboard never blanks to zeros.

**Phase 6b — App ⇄ web feature parity (port the web-only tools to iOS).** See §7
  for the live checklist. Active next step after the deploy.

**Phase 7 — Progressive onboarding + real hosting + subscriptions.** In-app nudge →
optional survey feeding the evolving persona. Move off the laptop dev server to
proper hosting (gunicorn on Heroku is the interim). RevenueCat subscriptions
(already scaffolded).

## 4b. Repos & deployment (the correct multi-platform layout)

**Rule: one shared brain (backend) deployed once; each platform is its own repo
pointing at that one backend.**

```
Brain (one backend = API):
   sandy-backend   → Heroku (single deploy; every platform talks to it)

Frontends (each its own repo + its own publish):
   sandy-web       (website)        → static web host
   sandy-apple     (iOS + Mac)      → App Store   (one Swift repo serves both)
   sandy-android   (Android)        → Google Play
   Windows         → same as web for now; its own repo later only if needed
```

Total: ~3–4 repos (backend + web + apple + android). The owner is already
half-right (backend and web are already separate repos). What changes:
- New backend deploy supersedes the old personal one (`sandy-robot`).
- iOS + Mac live in one Apple/Swift repo.
- Web frontend just needs to point at the NEW backend URL.
- Do NOT delete the old `sandy-robot` Heroku app until owner data is migrated.

## 4c. Secrets / environment for the new system

Current `.env.example` is the old single-user shape. For the clean product:

**KEEP (core brain + data):**
- `MONGODB_URI`, `MONGODB_DB_NAME` → set to the **new product DB** (e.g. `sandy-app`).
- `OPENAI_API_KEY`, `OPENAI_MODEL`; `GEMINI_API_KEY`.
- `AZURE_OPENAI_*` (chat deployment = router/brain), `AZURE_OPENAI_IMAGE_*` (image gen).
- Voice: `GEMINI_TTS_VOICE`, `SANDY_LIVE_MODEL` (Gemini Live); fallbacks
  `GOOGLE_APPLICATION_CREDENTIALS` + `GOOGLE_TTS_*`, `AZURE_SPEECH_*`.
- `EXA_API_KEY` (web research); `GOOGLE_PLACES_API_KEY`, `GOOGLE_CALENDAR_ID` (if kept).

**NEW (multi-tenant product — add these):**
- `JWT_SECRET` — signs user tokens (critical).
- `OWNER_PASSWORD` — owner dev login.
- `GOOGLE_OAUTH_CLIENT_ID`, `APPLE_BUNDLE_ID` — real user sign-in.
- `REVENUECAT_WEBHOOK_AUTH` — subscriptions.

**OWNER-TENANT integrations (admin-only, move to the owner tenant, not globals):**
- `SANDY_MQTT_HOST/PORT/USER/PASS` — owner robot/room.
- `GITHUB_TOKEN`, social platform tokens — owner admin tools only.
- Owner identity (`SANDY_USER_CHAT_ID`) → becomes the owner tenant id.

**DROP (legacy — remove entirely):**
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_SECRET_TOKEN`, `RUN_MODE`, `SANDY_COMMAND_MODE`.
- Robot device / hardware: `SANDY_IP`, `SANDY_ENABLE_*`, `SANDY_DEVICE_ID`, `SANDY_THING_ID`, `ARDUINO_CLIENT_*`.
- Camera: `CAM_*`.
- Vertex/Claude fixer (was the removed self-coding): `GOOGLE_CLOUD_PROJECT`, `VERTEX_REGION`, `CLAUDE_VERTEX_MODEL`.

Note: per-tenant config (persona, integrations) lives in the DB, NOT in env.

## 5. Open decisions — RESOLVED (2026-06-25)

- ~~Tenant id scheme~~ → fresh clean id = the owner's `sandy_users` uuid
  `3ab1c7f824c04e2aa3cd8bf0ca2f51d6` (legacy `628544372` kept only as the auth
  `provider_sub` for lookup + `OWNER_TENANT_ID` for the transitional device gates).
- ~~Copy vs clean DB~~ → copied (Phase 1 migration ran: 1080 docs into `sandy-app`).
- ~~When to shut down the old personal app~~ → the `sandy-robot` Heroku app was
  REPURPOSED to run the new backend (not shut down); the old `sany-db` is kept as a
  read-only backup until the owner is confident (a few weeks).
- ~~Hosting target~~ → Heroku for now (`gunicorn`); proper hosting is Phase 7.

## 6. Notes / gotchas

- iOS app has **two copies**: canonical `ios/SandyApp/` → `cp *.swift` to the Xcode
  build copy at `/Desktop/SandyApp/SandyApp/`. **Build from Xcode GUI**, not
  `xcodebuild` CLI (the iCloud-synced project folder makes the CLI link/asset phase
  hang for minutes on lazily-evicted files).
- Local dev server: `~/sandy_app_venv/bin/python cloud/serve_api.py` (venv is
  outside iCloud on purpose). Reach it via the stable Bonjour name
  `http://nabeelsul.local:8080` (survives LAN IP changes).
- Gemini Live voice already works in the app (`GeminiLiveManager.swift` → `/voice`
  WebSocket, owner JWT). Half-duplex, mouth lip-synced to her audio RMS.
- Owner constraints: never `git push` / deploy (owner does that); removals must be
  complete (no dead code); docs in English, chat in Arabic.

## 7. App ⇄ web feature parity (Phase 6b) — live checklist

The iOS app and the web (`sandy-web`) share one backend but expose different
surfaces. Already in BOTH: chat, tasks, reminders, habits/expenses/journal, Focus
(pomodoro + room scenes), Gemini Live voice.

**Web-only tools to PORT to iOS** (owner-requested 2026-06-25 — add all six):
  1. **Search** — web-research chat mode (`EXA`). Backend supported.
  2. **Images** — image-generation chat mode (Azure image). Backend supported.
  3. **Memory** — view/manage what Sandy remembers about you. **MUST be real data
     (no demo/fake payloads); surface anything any feature saves to memory in a
     proper, browsable way.** EXCLUDE the "Sandy system / منظومة" internals section.
  4. **Timeline** — your activity log.
  5. **Projects / Brainstorm** — plans/brainstorm tool.
  6. **Robot** — owner device control tab (room/robot over MQTT; owner-gated).

**Web tabs that are DEAD (backend removed — do NOT port; clean them off the web):**
  - **Emails** — the in-app Gmail feature was removed in Phase 3.
  - **GitHub issues** inside the web Projects tab — ops tooling removed in Phase 3.

Note: this parity work depends on Phase 4 for Memory to be truly per-tenant +
non-global; until then Memory reads the owner-scoped store.
