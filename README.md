# Sandy

Sandy is a voice-first personal assistant. She lives in a small desktop robot and
in a companion app for iPhone. You talk, she answers in her own voice,
she remembers you across sessions, and her personality can be tuned per user.

> **Goal number one: low-latency voice.** You speak, Sandy understands, Sandy
> answers back, with almost no delay. Every decision in this project is measured
> against that goal.

This repository holds the whole system: the backend, the iPhone app, and the
firmware for every board.

---

## How you reach her

| Surface | What it is |
|---|---|
| The robot | ESP32-S3 with a mic, speaker, display face, servo and sensors. Streams audio live to the backend over a WebSocket. |
| iPhone app | SwiftUI client — chat, voice, and the control surface for the robot and room devices. |

Same personality, same backend, same memory. Only the transport changes.

---

## Voice pipeline

Real-time, not file-based. The robot streams raw audio and gets audio back:

```
mic (I2S)  →  firmware  →  wss://…/voice   (HMAC handshake, anti-replay)
                              ↓
                       voice_ws session
                         ├─ speaker verification (local CAM++ via sherpa-onnx)
                         ├─ voice activity detection
                         ├─ tool dispatch (same tools as the text path)
                         └─ memory write-back
                              ↓
                       Gemini Live  →  audio back  →  speaker + lip-sync
```

The apps additionally fetch `POST /api/voice/tts` for Sandy's synthesized voice.

---

## The agent

One model call with native tools, in a loop (`cloud/app/brain/`):

```
held confirmation?  →  fast path (a bare device command, no model)  →
model  →  tool calls  →  results  →  model  …  (at most 6 calls)  →  reply
```

Twelve tools — `remember`, `recall`, `list_add`, `list_update`, `schedule`,
`schedule_update`, `summarize`, `device_control`, `scene_apply`, `web_search`,
`weather`, `image` — read and write three collections (the *blocks*): a log of
what happened, lists of things to do, and schedules of things that fire. Their
kinds come from one table (`blocks/kinds.py`), so a new kind of list or log entry
is a row there, not new code. Deletes, cancels and bulk changes wait for a yes.
The voice session runs the same tools, plus `confirm`.

## Memory

| Layer | Backing store |
|---|---|
| Short-term conversation | `sandy_stm`, one document per thread, TTL-expired; every channel sees the last turns of the others |
| What she knows | `fact` entries in the log, and the onboarding profile |
| Recall | the log's entries by embedding (Python cosine over the newest 400), text search without a key |
| Emotional moments | `mood` entries, the user's words Fernet-encrypted |

## Multi-tenancy

Every data operation goes through `ScopedCollection` (`cloud/app/utils/tenant_db.py`),
which stamps the caller's tenant onto every query and every insert. A caller
cannot widen its own scope. With no database *or* no authenticated tenant
`scoped(...)` returns `None`, and every store treats that as "read nothing, write nothing".

---

## Features

| Area | What it does |
|---|---|
| Conversation | Text and voice, one memory across both, short- and long-term |
| Lists, log & schedules | Tasks, shopping, goals, habits, reading, projects; expenses, journal, moods; reminders with recurrence and messages to your future self — all rows in the three blocks; confirmation before anything destructive |
| Focus | Pomodoro sessions that can start and end a scene |
| Room control | Saved scenes driving a room node over MQTT — lights, colour, music, fan, curtain. The node declares its outputs in its heartbeat, so its devices appear in the app on their own |
| Research | Web research and places lookup |
| Images | Generation, editing and description |
| Push | APNs delivery of reminders and the daily nudge (the app also rings reminders locally from `/api/schedules`) |

---

## Stack

```
Python 3.11 · Flask + gunicorn      backend
MongoDB                             all memory and feature stores
Azure OpenAI                        primary brain (chat with tools, vision)
Gemini                              Live voice and TTS
OpenAI                              fallback when Azure fails
Exa                                 web research
ESP-IDF / Arduino · MQTT            firmware and device transport
SwiftUI                             iPhone client
Heroku                              deployment
```

---

## Repository layout

```
cloud/            backend
  app/brain/        the agent: loop, tools, memory, confirmation, persona
  app/blocks/       the log, the lists, the schedules, and the kinds table
  app/api/          HTTP routes and the /voice WebSocket
  app/features/     devices, nodes, scenes, focus, photos, users, research …
  app/integrations/ external clients
  app/services/     APNs push, the schedule runner and the nudge scheduler
  app/utils/        tenancy, background thread pool, circuit breaker, profiles
firmware/         every board's program
  brain-core/     ESP32-S3 robot brain (ESP-IDF, C)
  vision-core/    ESP32-CAM (Arduino)
  room-node/      room controller (Arduino)
ios/              iPhone client (SwiftUI)
tests/  scripts/
```

---

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env   # repo root; .env.example lists every key
# Boot refuses to start without MONGODB_URI and a chat brain — the Azure trio
# (AZURE_OPENAI_ENDPOINT · AZURE_OPENAI_API_KEY · AZURE_OPENAI_CHAT_DEPLOYMENT)
# or OPENAI_API_KEY. Set JWT_SECRET too, or every login/token is refused.
# Every other key is optional; a missing one only disables its own feature.

python cloud/serve_api.py            # local dev server, port 8080
```

Production runs under gunicorn:

```
web: gunicorn --chdir cloud wsgi:app --workers 2 --threads 8 --timeout 120 --log-file -
```

Health check: `GET /health`.

## Tests

```bash
pip install pytest pytest-cov pytest-subtests mongomock ruff   # not in requirements.txt
python -m pytest tests/ -q
python -m pytest tests/ --cov=cloud/app --cov-report=term-missing
ruff check cloud/ scripts/
```

CI (`.github/workflows/tests.yml`) runs the suite plus `ruff`, `bandit`, and a
guard that fails the build if a secret-looking file is ever committed; it also
builds the ESP-IDF firmware and type-checks the iPhone app.

## Conventions

Code style and error-handling rules live in [CONVENTIONS.md](CONVENTIONS.md).
Board wiring is documented in
[firmware/brain-core/WIRING.md](firmware/brain-core/WIRING.md); build steps for
the iPhone app are in [ios/README_RUN.md](ios/README_RUN.md).
