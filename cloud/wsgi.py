#!/usr/bin/env python3
"""Production WSGI entrypoint: gunicorn --chdir cloud wsgi:app --workers 2 --threads 8 --timeout 120."""

from __future__ import annotations

from pathlib import Path

# Load .env before importing the app — some modules read env at import time.
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.bootstrap import bootstrap, configure_logging, init_runtime  # noqa: E402  (env must load before app imports)
from app.api.server import create_app  # noqa: E402
from app.config import APP_ENV, LOG_LEVEL  # noqa: E402
from app.db import get_db  # noqa: E402

# Logging first, so init_runtime's Mongo connection report isn't swallowed.
configure_logging(LOG_LEVEL)
init_runtime()
app = create_app(mongo_db=get_db())
bootstrap(app_env=APP_ENV, app=app)
