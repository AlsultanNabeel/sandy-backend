# Sandy

Sandy is a voice-first personal assistant. She lives in a small desktop robot and
in companion apps for iPhone and Android. You talk, she answers in her own voice,
she remembers you across sessions, and her personality can be tuned per user.

> **Goal number one: low-latency voice.** You speak, Sandy understands, Sandy
> answers back, with almost no delay. Every decision in this project is measured
> against that goal.

This repository holds the whole system: the backend, both mobile apps, and the
firmware for every board.

---

## How you reach her

| Surface | What it is |
|---|---|
| The robot | ESP32-S3 with a mic, speaker, display face, servo and sensors. Streams audio live to the backend over a WebSocket. |
| iPhone app | SwiftUI client — chat, voice, and the control surface for the robot and room devices. |
| Android app | Kotlin + Compose client against the same backend. Foundation stage. |

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

One function-calling pass over the real tool schemas, then a fixed graph:

```
fc_router  →  soul  →  router  →  ┬ pending  ┐
                                  ├ execute  ├→  response
                                  └ clarify  ┘
```

- **fc_router** — a single model call sees all registered tools and either calls
  one (or several) or replies in plain text.
- **soul** — injects the persona, emotional context and wellness signals.
- **execute** — runs the tool through the dispatcher.
- **response** — shapes the final reply.

State flows through a single typed `SandyState`. No globals. Adding a capability
means registering a tool, not editing the router.

## Memory

| Layer | Backing store |
|---|---|
| Short-term conversation | MongoDB, TTL-expired, one document per chat |
| Facts | MongoDB |
| Semantic recall | MongoDB Vector Search, degrades safely without the index |
| Emotional long-term | Encrypted (Fernet) |

Plus per-user tracking of interests, style, lessons, relationships and shared
history — all of it feeding the persona.

## Multi-tenancy

Every data operation goes through `ScopedCollection` (`app/utils/tenant_db.py`),
which stamps the caller's tenant onto every query and every insert. A caller
cannot widen its own scope. With no database *or* no authenticated tenant it
returns `None`, and every store treats that as "read nothing, write nothing".

---

## Features

| Area | What it does |
|---|---|
| Conversation | Text and voice, mood-aware, short- and long-term memory |
| Tasks & reminders | Create, edit, complete, delete; recurrence; confirmation before anything destructive |
| Life tracking | Shopping, habits with streaks, expenses, journal, reading log, Pomodoro focus |
| Room control | Saved scenes driving a room node over MQTT — lights, colour, music, fan, curtain. The node declares its outputs in its heartbeat, so its devices appear in the app on their own |
| Research | Web research and places lookup |
| Images | Generation, editing and description |
| Documents | TXT, PDF, DOCX, CSV, XLSX, JSON |
| Push | APNs delivery for reminders and the daily nudge |

---

## Stack

```
Python 3.11 · Flask + gunicorn      backend
MongoDB                             all memory and feature stores
Azure OpenAI                        primary brain (routing, chat, vision)
Gemini                              Live voice, TTS, and a routing fallback
OpenAI · AWS Bedrock                further fallbacks
Azure Speech                        speech to text
Exa                                 web research
ESP-IDF / Arduino · MQTT            firmware and device transport
SwiftUI · Kotlin Compose            iPhone and Android clients
Heroku                              deployment
```

---

## Repository layout

```
cloud/            backend
  app/agent/        graph · nodes · tools · executor · memory layers
  app/api/          HTTP routes and the /voice WebSocket
  app/features/     feature stores (tasks, reminders, life, devices …)
  app/integrations/ external clients
  app/utils/        tenancy, rate limiting, circuit breaker, profiles
firmware/         ESP32-S3 robot brain (ESP-IDF, C)
vision-core/      ESP32-CAM
sandy/            classic ESP32 node
room-node/        room controller (Arduino)
ios/  android/    mobile clients
tests/  scripts/
```

---

## Running it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# create .env at the repo root — see .env.example for the full list.
# Minimum to boot: AZURE_OPENAI_ENDPOINT · AZURE_OPENAI_API_KEY
#                  AZURE_OPENAI_CHAT_DEPLOYMENT · MONGODB_URI · JWT_SECRET
# Every other key is optional; a missing one only disables its own feature.

python cloud/serve_api.py            # local dev server
```

Production runs under gunicorn:

```
web: gunicorn --chdir cloud wsgi:app --workers 2 --threads 8 --timeout 120
```

Health check: `GET /health`.

## Tests

```bash
python -m pytest tests/ -q
python -m pytest tests/ --cov=cloud/app --cov-report=term-missing
ruff check cloud/ scripts/
```

CI runs the suite plus `ruff`, `bandit`, and a guard that fails the build if a
secret-looking file is ever committed.

## Conventions

Code style and error-handling rules live in [CONVENTIONS.md](CONVENTIONS.md).
Board wiring is documented in
[firmware/brain-core/WIRING.md](firmware/brain-core/WIRING.md); build steps for
the clients are in [ios/README_RUN.md](ios/README_RUN.md) and
[android/README.md](android/README.md).
