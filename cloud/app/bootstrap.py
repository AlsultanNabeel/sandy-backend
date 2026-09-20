"""One-time startup initialization for Sandy.

Call bootstrap() once at the top of main() before anything else runs.
All functions here are idempotent — safe to call multiple times.
"""

import logging
import os

logger = logging.getLogger(__name__)

# Third-party loggers that are noisy by default
_QUIET_LOGGERS = (
    "pymongo",
    "pymongo.topology",
    "pymongo.serverSelection",
    "pymongo.connection",
    "pymongo.command",
    "httpx",
    "httpcore",
    "urllib3",
    # Gemini Live's transport: at DEBUG it logs EVERY audio frame (thousands of
    # lines per voice session). Pinned to WARNING even when LOG_LEVEL=DEBUG.
    "websockets",
    "websockets.client",
    "websockets.protocol",
    "apscheduler",
    "openai",
    "openai._base_client",
    "anthropic",
    "boto3",
    "botocore",
    "s3transfer",
    "google",
    "google.auth",
    "google.api_core",
    "asyncio",
    "bedrock",
    "bedrock-runtime",
)

# Endpoints the frontend polls on a timer — their werkzeug access lines are pure
# noise (once a minute, forever). We can only drop our half; Heroku's router logs
# the same request and that's outside the app.
_QUIET_ACCESS_PATHS = ("/api/reminders",)


class _DropPollingAccess(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        return not any(p in msg for p in _QUIET_ACCESS_PATHS)


def configure_logging(log_level: str = "INFO") -> None:
    """Set up root logger. Safe to call multiple times."""
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    # Drop the frontend's per-minute reminder poll from werkzeug's access log.
    _wz = logging.getLogger("werkzeug")
    if not any(isinstance(f, _DropPollingAccess) for f in _wz.filters):
        _wz.addFilter(_DropPollingAccess())
    logger.debug("[Bootstrap] Logging configured at %s level", log_level)


def write_google_credentials() -> None:
    """Write GOOGLE_CREDENTIALS_JSON env var to a key file on disk.

    Heroku can't store key files, so the JSON is stored as an env var and
    written to disk on startup so Google SDK can find it via
    GOOGLE_APPLICATION_CREDENTIALS.
    """
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if not creds_json:
        return
    key_path = "sandy-gcloud-key.json"
    try:
        # Owner-only (0600): this is a service-account private key, and `open(…,
        # "w")` made it world-readable on any machine with a normal umask.
        fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(creds_json)
        os.chmod(key_path, 0o600)   # an existing file keeps its old mode otherwise
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(key_path)
        logger.debug("[Bootstrap] Google credentials written to %s", key_path)
    except OSError as exc:
        logger.warning("[Bootstrap] Failed to write Google credentials: %s", exc)


def ensure_data_dirs() -> None:
    """Create runtime data directories if they don't exist."""
    from app.config import TASKS_DIR

    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug("[Bootstrap] Data directories ready")


def ensure_indexes() -> None:
    """Create every boot-time index, each one independently.

    Lifted out of ``bootstrap()`` so it can be called on its own and asserted
    against — an index that quietly failed to be created is invisible from the
    outside and shows up only as everything being slower, which is the least
    debuggable shape a fault can take.

    Runs on the raw handle by design: this is boot, before any request has set a
    tenant. Every index leads with the field the tenant scoping filters on.
    """
    from app.agent.health_monitor import ensure_ttl_index
    from app.db import get_db

    mongo_db = get_db()
    try:
        ensure_ttl_index(mongo_db)
    except Exception as exc:  # noqa: BLE001 — external call edge (Mongo)
        logger.warning("[Bootstrap] ensure_ttl_index failed: %s", exc)
    if mongo_db is None:
        return

    # Each index is created independently so one failure doesn't silently
    # skip the rest. (label, callable) pairs keep the logging cheap.
    index_jobs = [
        ("web_chat_history.expire_at", lambda: mongo_db.web_chat_history.create_index(
            "expire_at", expireAfterSeconds=0, background=True
        )),
        ("sandy_session_state.chat_id", lambda: mongo_db.sandy_session_state.create_index(
            "chat_id", unique=True, background=True
        )),
        ("sandy_evals.chat_id+created_at", lambda: mongo_db.sandy_evals.create_index(
            [("chat_id", 1), ("created_at", -1)], background=True
        )),
        ("guest_usage.jti+chat_type", lambda: mongo_db.guest_usage.create_index(
            [("jti", 1), ("chat_type", 1)], unique=True, background=True
        )),
        ("guest_usage.last_request_at", lambda: mongo_db.guest_usage.create_index(
            "last_request_at", background=True
        )),
        ("guest_usage.created_at_ttl", lambda: mongo_db.guest_usage.create_index(
            "created_at", expireAfterSeconds=60 * 60 * 24 * 90, background=True
        )),
        ("sandy_pending_state.updated_at_ttl", lambda: mongo_db.sandy_pending_state.create_index(
            "updated_at", expireAfterSeconds=60 * 60, background=True
        )),
        # `sandy_memories` had no index at all, and it is the collection that
        # grows fastest — every conversation summary, fact, relationship and
        # lesson lands here and nothing expires. Both of its hot readers scanned
        # the whole thing on every message:
        # `context_builder.get_persona_directives` (filters chat_id + label,
        # sorts created_at) and the keyword fallback in
        # `semantic_memory.search_relevant_summaries`. This is the index that
        # stops Sandy getting slower the longer she is used.
        ("sandy_memories.chat_id+label+created_at", lambda: mongo_db.sandy_memories.create_index(
            [("chat_id", 1), ("label", 1), ("created_at", -1)], background=True
        )),
        # صفّ لكل (مستأجر، نسخة)، والنسخة بتتحرّك مع كل كتابة — يعني الصفوف
        # بتتراكم وما في مين يشيلها. الصفّ اللي عمره شهر ما إلو مين يسأل عنه:
        # نسخته راحت من زمان.
        ("sandy_prompt_cache.created_at_ttl",
         lambda: mongo_db.sandy_prompt_cache.create_index(
             "created_at", expireAfterSeconds=60 * 60 * 24 * 30, background=True
         )),
        ("camera_inbox.expire_at_ttl", lambda: mongo_db.camera_inbox.create_index(
            "expire_at", expireAfterSeconds=0, background=True
        )),
        # Popped on every chat message (passive delivery of due messages).
        ("sandy_future_messages.chat_id+delivered+deliver_at",
         lambda: mongo_db.sandy_future_messages.create_index(
             [("chat_id", 1), ("delivered", 1), ("deliver_at", 1)], background=True
         )),
        # Read twice on every chat reply (`dreams_engine.get_dreams_context` and
        # `proactive_goals.get_goals_followup_context`, both chat_id + status),
        # and no module created an index for it — each read scanned every
        # goal on the server.
        ("sandy_goals.chat_id+status+updated_at", lambda: mongo_db.sandy_goals.create_index(
            [("chat_id", 1), ("status", 1), ("updated_at", 1)], background=True
        )),
        # Found by the 19 Sep 2026 audit: each query below filtered or sorted on
        # fields no index covered, so it scanned the whole collection.
        # the conversation list and search
        ("conversations.user_id+updated_at", lambda: mongo_db.conversations.create_index(
            [("user_id", 1), ("updated_at", -1)], background=True
        )),
        # the active session and history
        ("sandy_focus.user_id+state+started_at", lambda: mongo_db.sandy_focus.create_index(
            [("user_id", 1), ("state", 1), ("started_at", -1)], background=True
        )),
        # focus stats by day
        ("sandy_focus.user_id+state+ended_at", lambda: mongo_db.sandy_focus.create_index(
            [("user_id", 1), ("state", 1), ("ended_at", 1)], background=True
        )),
        # the habit list
        ("sandy_habits.user_id+archived+created_at", lambda: mongo_db.sandy_habits.create_index(
            [("user_id", 1), ("archived", 1), ("created_at", 1)], background=True
        )),
        # reads sort by `at`, the old index is on `date`
        ("sandy_journal.user_id+at", lambda: mongo_db.sandy_journal.create_index(
            [("user_id", 1), ("at", -1)], background=True
        )),
        # reading stats filter on `ended_at`
        ("sandy_reading_sessions.user_id+state+ended_at", lambda: mongo_db.sandy_reading_sessions.create_index(
            [("user_id", 1), ("state", 1), ("ended_at", 1)], background=True
        )),
        # the once-a-minute cross-tenant due scan
        ("sandy_scene_timers.fire_at", lambda: mongo_db.sandy_scene_timers.create_index(
            [("fire_at", 1)], background=True
        )),
        # the gifts list
        ("sandy_gifts.chat_id+created_at", lambda: mongo_db.sandy_gifts.create_index(
            [("chat_id", 1), ("created_at", -1)], background=True
        )),
        # the saved-content list
        ("sandy_shared_content.chat_id+created_at", lambda: mongo_db.sandy_shared_content.create_index(
            [("chat_id", 1), ("created_at", -1)], background=True
        )),
    ]
    for label, job in index_jobs:
        try:
            job()
        except Exception as exc:  # noqa: BLE001 — external call edge (Mongo)
            logger.warning("[Bootstrap] create_index %s failed: %s", label, exc)


def bootstrap(app_env: str = "prod", app=None) -> None:
    """Run all one-time startup tasks.

    Call this once at the top of main(), before starting the bot runtime.

    Args:
        app_env: Runtime environment name ('dev' | 'prod').
        app:     Flask app instance, forwarded to Sentry for FlaskIntegration.
    """
    from app.config import LOG_LEVEL, validate_config

    configure_logging(LOG_LEVEL)

    fatal, warnings = validate_config()
    for msg in warnings:
        logger.warning("[Bootstrap] config warning: %s", msg)
    if fatal:
        for msg in fatal:
            logger.error("[Bootstrap] config error: %s", msg)
        raise RuntimeError("Sandy cannot start: " + "; ".join(fatal))

    write_google_credentials()
    ensure_data_dirs()

    # Before anything that can fail, so the first thing that breaks is reported
    # rather than swallowed. A no-op when SENTRY_DSN is unset.
    try:
        from app.integrations.error_tracking import init_error_tracking

        init_error_tracking()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Bootstrap] error tracking failed to start: %s", exc)


    try:
        from app.agent.tools.setup import register_all_tools

        register_all_tools()
    except Exception as exc:
        logger.warning("[Bootstrap] Tools registration failed: %s", exc)

    try:
        ensure_indexes()
    except Exception as exc:
        logger.warning("[Bootstrap] Mongo index setup failed: %s", exc)

    try:
        from app.agent.semantic_memory import migrate_summary_threads
        from app.db import get_db

        migrate_summary_threads(get_db())
    except Exception as exc:
        logger.warning("[Bootstrap] summary migration failed: %s", exc)

    # Daily push nudge — stays idle until APNs is configured (paid Apple keys).
    try:
        from app.db import get_db
        from app.services.nudge_scheduler import start_nudge_scheduler
        start_nudge_scheduler(get_db())
    except Exception as exc:
        logger.warning("[Bootstrap] nudge scheduler start failed: %s", exc)

    # Scene timed reverts ("movie for two hours, then lights on") — once a minute.
    try:
        from app.db import get_db
        from app.services.scene_timer_runner import start_scene_timer_runner
        start_scene_timer_runner(get_db())
    except Exception as exc:
        logger.warning("[Bootstrap] scene timer runner start failed: %s", exc)

    logger.debug("[Bootstrap] Startup complete (env=%s)", app_env)
