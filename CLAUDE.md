# Sandy-App — repo guide for Claude Code

**Read `PRODUCT_MIGRATION_PLAN.md` first** — it holds the product vision (clean
multi-tenant, owner = tenant #1, drop Telegram, one backend + many frontends) and
the ordered migration plan. Start there before any backend work.

## Layout
- `cloud/` — the Python backend (the brain / API). Run locally:
  `~/sandy_app_venv/bin/python cloud/serve_api.py` (venv is outside iCloud).
  Reach it at `http://nabeelsul.local:8080` (stable Bonjour name; survives IP changes).
- `ios/SandyApp/` — the SwiftUI iOS app (canonical copy). It is mirrored to the
  Xcode build copy at `/Desktop/SandyApp/SandyApp/` via `cp *.swift`. **Build from
  the Xcode GUI, not `xcodebuild` CLI** (iCloud-synced folder hangs the CLI).

## Owner constraints (hard rules)
- Never `git push` or deploy — the owner does that. Commit locally and say it's ready.
- Removals must be complete: no dead/unused code left behind.
- Docs (README/CLAUDE/plans) in English; chat with the owner in Arabic.
