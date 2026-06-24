#!/usr/bin/env python3
"""Production WSGI entrypoint for gunicorn.

``serve_api.py`` is the local dev runner (Flask's built-in werkzeug server, single
process — fine for a laptop, but it serializes requests and chokes when a screen
fires several calls at once). In production we run this module under gunicorn with
multiple workers/threads so requests are served concurrently:

    gunicorn --chdir cloud wsgi:app --workers 2 --threads 8 --timeout 120

It builds the SAME app as ``serve_api.main()`` but exposes a module-level ``app``
object for gunicorn to import. The ``/voice`` WebSocket (flask-sock) runs inside a
worker thread, which the threaded worker handles fine.
"""

from __future__ import annotations

import importlib
from pathlib import Path

# Load .env before importing the app — some modules read env at import time.
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.bootstrap import bootstrap  # noqa: E402  (env must load before app imports)
from app.api.server import create_app  # noqa: E402
from app.config import APP_ENV  # noqa: E402

# The facade module holds the shared mongo client (re-exported as a submodule so
# the package's ``agent`` instance doesn't shadow it).
_facade = importlib.import_module("app.agent.facade.agent")

app = create_app(mongo_db=_facade.mongo_db)
bootstrap(app_env=APP_ENV, app=app)
