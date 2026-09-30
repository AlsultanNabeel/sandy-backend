"""One-time, idempotent startup: config check, logging, Sentry, indexes, schedulers."""

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
    # Logs every audio frame at DEBUG; pinned to WARNING.
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

def configure_logging(log_level: str = "INFO") -> None:
    """Set up root logger. Safe to call multiple times."""
    logging.basicConfig(
        level=getattr(logging, log_level, logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    for name in _QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
    logger.debug("[Bootstrap] Logging configured at %s level", log_level)


def write_google_credentials() -> None:
    """Write GOOGLE_CREDENTIALS_JSON to a key file (Heroku can't store files) for GOOGLE_APPLICATION_CREDENTIALS."""
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON", "").strip()
    if not creds_json:
        return
    key_path = "sandy-gcloud-key.json"
    try:
        # 0600: it's a service-account private key.
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
    """Create every boot-time index independently (on the raw handle, before any tenant)."""
    from app.agent.health_monitor import ensure_ttl_index
    from app.db import get_db

    mongo_db = get_db()
    try:
        ensure_ttl_index(mongo_db)
    except Exception as exc:  # noqa: BLE001 — external call edge (Mongo)
        logger.warning("[Bootstrap] ensure_ttl_index failed: %s", exc)
    if mongo_db is None:
        return

    # One failure must not skip the rest.
    index_jobs = [
        ("sandy_session_state.chat_id", lambda: mongo_db.sandy_session_state.create_index(
            "chat_id", unique=True, background=True
        )),
        ("sandy_evals.chat_id+created_at", lambda: mongo_db.sandy_evals.create_index(
            [("chat_id", 1), ("created_at", -1)], background=True
        )),
        ("sandy_pending_state.updated_at_ttl", lambda: mongo_db.sandy_pending_state.create_index(
            "updated_at", expireAfterSeconds=60 * 60, background=True
        )),
        # Hot on every message (persona directives, summary search); grows fastest.
        ("sandy_memories.chat_id+label+created_at", lambda: mongo_db.sandy_memories.create_index(
            [("chat_id", 1), ("label", 1), ("created_at", -1)], background=True
        )),
        # صفّ لكل (مستأجر، نسخة) بيتراكم؛ القديم ما حدا بيسأل عنه.
        ("sandy_prompt_cache.created_at_ttl",
         lambda: mongo_db.sandy_prompt_cache.create_index(
             "created_at", expireAfterSeconds=60 * 60 * 24 * 30, background=True
         )),
        # بصمات تواقيع رفع الكاميرا — بتعيش قدّ نافذة الإعادة وبتنمسح لحالها.
        ("cam_upload_nonces.expire_at_ttl", lambda: mongo_db.cam_upload_nonces.create_index(
            "expire_at", expireAfterSeconds=0, background=True
        )),
        ("camera_inbox.expire_at_ttl", lambda: mongo_db.camera_inbox.create_index(
            "expire_at", expireAfterSeconds=0, background=True
        )),
        # رموز إثبات الحضور للربط — خمس دقايق وبتروح لحالها.
        ("node_pair_challenges.expires_at_ttl",
         lambda: mongo_db.node_pair_challenges.create_index(
             "expires_at", expireAfterSeconds=0, background=True
         )),
        ("node_pair_challenges.node_tenant",
         lambda: mongo_db.node_pair_challenges.create_index(
             [("node_id", 1), ("tenant", 1)], unique=True, background=True
         )),
        # Popped on every chat message (passive delivery of due messages).
        ("sandy_future_messages.chat_id+delivered+deliver_at",
         lambda: mongo_db.sandy_future_messages.create_index(
             [("chat_id", 1), ("delivered", 1), ("deliver_at", 1)], background=True
         )),
        # Read on every chat reply (chat_id + status).
        ("sandy_goals.chat_id+status+updated_at", lambda: mongo_db.sandy_goals.create_index(
            [("chat_id", 1), ("status", 1), ("updated_at", 1)], background=True
        )),
        # The conversation list and search.
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
    """Run all one-time startup tasks (app_env: 'dev'|'prod'; app: Flask app for Sentry)."""
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

    # First, so the first failure is reported. No-op without SENTRY_DSN.
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

    # ── Periodic jobs: one worker per machine (kernel file lock) ─────────────
    # Per-day / per-timer claims still make them safe across dynos. mqtt_ingest
    # is deliberately not elected: each worker keeps its own listener.
    from app.utils.process_leader import claim_leadership

    if claim_leadership("schedulers"):
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

        # sandy_schedules (the blocks) — once a minute; alongside the old runners, not instead.
        try:
            from app.blocks import init_blocks
            from app.db import get_db
            from app.services.schedule_runner import start_schedule_runner
            init_blocks(get_db())
            start_schedule_runner(get_db())
        except Exception as exc:
            logger.warning("[Bootstrap] schedule runner start failed: %s", exc)

    logger.debug("[Bootstrap] Startup complete (env=%s)", app_env)
