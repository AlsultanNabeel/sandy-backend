#!/usr/bin/env python3
"""Local HTTP API server for the iOS app (development only).

Serves the exact same Flask app as production (``/api/auth``, ``/api/onboarding``,
``/api/subscription``, ``/api/agent`` …) on port 8080, but WITHOUT Telegram
polling or webhook — so it never touches the production bot.

This launcher exists because ``RUN_MODE=polling`` starts Telegram polling only
and does not serve the HTTP API, while webhook mode would register a Telegram
webhook URL. Neither is what the mobile client needs locally.

Run from the repo root:
    python cloud/serve_api.py

Optional: set ``MONGODB_DB_NAME=sandy_app_test`` in ``.env`` to keep test data
out of the real database.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

# حمّل الـ .env (جذر المستودع) قبل أي استيراد للتطبيق — بعض الوحدات (مثل
# gemini_tts) تقرأ متغيّرات البيئة وقت الاستيراد، فلازم تكون جاهزة قبلها.
# override=True حتى قيم الملف تغلب على أي افتراضي عالق.
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.bootstrap import bootstrap

# Import the runtime *module* explicitly: the facade package re-exports an
# ``agent`` instance, so ``from app.agent.facade import agent`` would shadow the
# submodule. importlib gives us the module that holds ``telegram_webhook_runtime``.
facade = importlib.import_module("app.agent.facade.agent")


def main() -> None:
    app = facade.telegram_webhook_runtime["app"]
    bootstrap(app_env=facade.APP_ENV, app=app)
    port = int(os.getenv("PORT", "8080"))
    print("=" * 60)
    print(f"🦞 Sandy HTTP API (no Telegram) → http://localhost:{port}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port)  # nosec B104 — local dev only


if __name__ == "__main__":
    main()
