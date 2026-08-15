# Contributing

## Getting it running

**Backend** — Python 3.11:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # fill in at least the five keys marked required
python cloud/serve_api.py
```

A missing optional key disables only its own feature; the app still boots. That
is deliberate, so you never need every credential to work on one thing.

**Tests** — no database, no hardware, no credentials:

```bash
python -m pytest tests/ -q
ruff check cloud/ scripts/
```

If collection dies on an OpenSSL symbol, you need `pyOpenSSL>=23.2.0`.

**iPhone app** — see [ios/README_RUN.md](ios/README_RUN.md). Build from the Xcode
GUI; `xcodebuild` on the command line hangs on the iCloud-synced folder.

**Firmware** — see [firmware/brain-core/WIRING.md](firmware/brain-core/WIRING.md).
`idf.py build` before every flash.

## Before you write anything

Read [`ARCHITECTURE_MAP.md`](ARCHITECTURE_MAP.md) — the whole file. It describes
every layer, the contracts between them, and the known defects. It exists so that
nobody has to rediscover the same things halfway through a change.

Then read [CONVENTIONS.md](CONVENTIONS.md) for the rules every change follows.

## What good looks like here

**Comments explain why, not what.** The code already says what it does. A comment
earns its place by recording the reason a decision was made, the thing that was
tried and failed, or the constraint that is not visible from the line itself.
Look at `tenant_db.py` or the uplink buffer in `sandy_voice.c` for the register.

**Removals are complete.** No dead code, no orphan imports, no wiring left
dangling. A function nobody calls is worse than a missing feature: it looks like
it works.

**Errors are loud.** Never `except Exception: pass`. Catch the narrowest
exception you can; broad catches belong only at real boundaries — a background
thread, a request handler, an external call.

**One commit, one change.** The message should say what changed and *why the old
way was wrong*. Subject in the imperative, English.

**A contract change updates the map in the same commit.** A topic, a route, an
ownership rule. A map that lies is worse than no map.

## Tests

New behaviour needs a test, and the interesting tests are the ones that pin down
a guarantee rather than a happy path — cross-tenant access being refused, a
malformed payload not crashing a background thread, a timeout returning nothing
rather than half an answer.

`tests/test_device_system.py` is the model to copy.

## Language

Documentation, comments and commit messages in English. The app's own text lives
in `ios/SandyApp/Localization/` and nowhere else — never a literal string in a
view.

Within that: **interface text is Modern Standard Arabic, Sandy's own replies keep
her dialect.** Buttons, labels, errors and empty states are the system speaking
and have to read clearly to every Arabic speaker. What she says in conversation
is her personality, and it stays.
