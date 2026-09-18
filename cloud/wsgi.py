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

from pathlib import Path

# Load .env before importing the app — some modules read env at import time.
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)

from app.bootstrap import bootstrap, configure_logging  # noqa: E402  (env must load before app imports)
from app.agent.facade.agent import init_runtime  # noqa: E402
from app.api.server import create_app  # noqa: E402
from app.config import APP_ENV, LOG_LEVEL  # noqa: E402
from app.db import get_db  # noqa: E402

# Logging first: `init_runtime` connects Mongo and logs what it found, and
# before this those lines went to Python's last-resort handler (WARNING and up)
# — the connection report was the one thing silenced. `bootstrap` calls it
# again; `basicConfig` makes the second call a no-op.
configure_logging(LOG_LEVEL)
# Explicit runtime init (no import-time side effects): connect Mongo, register the
# shared handle on app.db, initialize the feature stores, start ingest.
init_runtime()
app = create_app(mongo_db=get_db())
bootstrap(app_env=APP_ENV, app=app)
