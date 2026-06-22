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
  2. REMOVE in-app ops/admin agent tools (owner does ops outside): GitHub
     (`integrations/github_api.py`, `heroku_tool.py`, incident/deploy tooling) and
     their tool schemas — wherever they were owner-gated.
  3. DE-HARDCODE the owner: drop the `628544372`/`SANDY_USER_CHAT_ID` fallback and
     the `is_owner`/`role=="owner"`/`active_profile_allows_privileged_access`
     branches that gate *a user's own data*. Every authenticated user gets full
     CRUD on THEIR data (productivity_api already does this via guest-vs-user).
  4. ENFORCE fail-closed: stores refuse a read/write when `current_user_id()` is
     None (the security core). Do this last + test carefully.
  KEEP (do NOT remove): the guest-vs-authenticated gating (`_is_guest`, demo
  payloads for visitors) — that is visitor limiting, not owner privilege. Robot/
  room stay the owner's device controls transitionally (his only hardware), per
  the per-tenant device-controls model above.

  Footprint to touch (owner-gating): `api/{productivity,life,emails,server,
  voice_ws,auth_handlers}.py`, `features/gmail.py`, `agent/memory.py`,
  `agent/graph/graph.py`, `agent/nodes/execute.py`,
  `agent/executor/{task,reminder}_handlers.py`, `utils/user_profiles.py`.
  Not started yet — implement in a fresh session, chunk by chunk, boot-tested.

**Phase 4 — Close the globals.** `search_relevant_facts` becomes per-tenant.
Persona becomes a per-tenant field (starts pleasant, evolves with use).

**Phase 5 — Unify routes.** life/productivity APIs serve any tenant (no owner-only,
no demo payloads). Robot/room actuation gated to the owner tenant only.

**Phase 6 — Frontends.** One backend serving iOS (done) + Web (`sandy-web`
repointed) → then Android / Mac / Windows.

**Phase 7 — Progressive onboarding + real hosting + subscriptions.** In-app nudge →
optional survey feeding the evolving persona. Move off the laptop dev server to
proper hosting. RevenueCat subscriptions (already scaffolded).

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

## 5. Open decisions (need owner input)

- Tenant id scheme for the owner (keep `628544372`, or a fresh clean id?).
- Whether to copy the owner's data into the product DB or start the product clean
  and re-seed only what he wants.
- When to physically shut down the Telegram bot / personal Heroku app.
- Hosting target for the product backend.

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

## 7. Status of app-vs-web parity (separate, smaller track)

Done this session: habit undo, completed-tasks filter, reminder delete, Focus tab
(pomodoro + room scenes control), scrollable tab bar, Gemini Live voice.
Remaining web tabs to port: **Robot**, **Emails**, **Search/Images** chat modes.
These can proceed in parallel but are lower priority than the migration above.
