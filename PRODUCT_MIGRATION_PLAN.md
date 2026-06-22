# Sandy — Product Migration Plan (clean multi-tenant)

> Bootstrap doc for a fresh Claude Code session in this repo. Read this first.
> Chat with the owner is in Arabic; this doc is English (repo convention).

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
- **Robot/room kept but owner-only.** The owner uses the app as his personal Sandy
  (real `room-node` control over MQTT). No other user sees the Robot/Room tabs or
  can actuate his hardware.

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
- Owner = tenant #1 with an **admin role flag** (a tenant attribute), not a
  hardcoded branch. Admin powers (his robot/room, social, ops tools) are gated by
  that role on his tenant.
- **Per-tenant config** replaces globals: persona (evolving), integrations
  (robot/room MQTT topics), preferences — all stored on the tenant.
- Frontends are thin clients over the same API (iOS done; Web = reuse `sandy-web`
  repointed; Android/Mac/Windows later).

## 4. Migration phases (ordered)

**Phase 0 — Setup.** Work stays in `Sandy-App` (already a separate repo). Snapshot
/ branch before structural changes.

**Phase 1 — Product DB + migrate owner as tenant #1.** New `MONGODB_DB_NAME`
(e.g. `sandy-app`). Migration script moves the owner's data (currently tagged with
his id, plus any legacy `user_id=None`) into a clean tenant id across all stores:
tasks, reminders, habits, expenses, scenes, summaries, facts, journal, onboarding.

**Phase 2 — Remove Telegram completely.** Delete `telegram_handlers.py`, bot
registration, Telegram `/webhook` routes, `pyTelegramBotAPI` from requirements, and
every Telegram branch. Clean deletion — no dead/unused code left behind.

**Phase 3 — Enforce tenant (fail-closed) + de-owner.** Any data access without a
tenant is rejected. Convert the ~18 owner branches into a tenant `role=admin`
attribute. Owner stops being a special code path.

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
