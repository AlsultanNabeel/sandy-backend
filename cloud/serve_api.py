#!/usr/bin/env python3
"""Local dev server (port 8080): python cloud/serve_api.py. Production uses wsgi.py."""

from __future__ import annotations

import os
from pathlib import Path

# حمّل الـ .env قبل أي استيراد للتطبيق (بعض الوحدات بتقرا البيئة وقت الاستيراد).
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.bootstrap import bootstrap  # noqa: E402  (env must load before app imports)


def main() -> None:
    from app.api.server import create_app
    from app.bootstrap import configure_logging, init_runtime
    from app.config import APP_ENV, LOG_LEVEL
    from app.db import get_db

    # Logging before init_runtime so its connection report shows (see wsgi.py).
    configure_logging(LOG_LEVEL)
    init_runtime()
    app = create_app(mongo_db=get_db())
    bootstrap(app_env=APP_ENV, app=app)
    port = int(os.getenv("PORT", "8080"))
    print("=" * 60)
    print(f"🦞 Sandy HTTP API → http://localhost:{port}")
    print("=" * 60)
    app.run(host="0.0.0.0", port=port)  # nosec B104 — local dev only


if __name__ == "__main__":
    main()
