"""One-time, idempotent startup: the runtime (Mongo, stores, MQTT), then config
check, Sentry, indexes and the schedulers.

Nothing connects at *import* time, so the package imports in a test with no
credentials; the entrypoints call `init_runtime()` then `bootstrap()`.
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
    # Logs every audio frame at DEBUG; pinned to WARNING.
    "websockets",
    "websockets.client",
    "websockets.protocol",
    "apscheduler",
    "openai",
    "openai._base_client",
    "google",
    "google.auth",
    "google.api_core",
    "asyncio",
)

_initialized = False

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


def init_runtime() -> None:
    """Connect Mongo, register it on `app.db`, create the stores' indexes, start
    MQTT ingest. Idempotent."""
    global _initialized
    if _initialized:
        return
    from app.config import MONGODB_DB_NAME, MONGODB_URI
    from app.db import configure
    from app.features.device_store import init_device_store
    from app.features.focus_store import init_focus_store
    from app.features.node_store import init_node_store
    from app.features.photo_album import init_photo_album
    from app.features.push_tokens_store import init_push_tokens_store
    from app.features.scene_store import init_scene_store
    from app.features.speaker_id import init_speaker_store
    from app.features.usage_store import init_usage_store
    from app.features.users_store import init_users_store
    from app.integrations.mongodb_store import init_mongo_connection
    from app.integrations.mqtt_ingest import start_mqtt_ingest

    _client, mongo_db = init_mongo_connection(MONGODB_URI, MONGODB_DB_NAME)
    # Every store reads the one handle through app.db.get_db().
    configure(mongo_db)
    for init in (init_users_store, init_speaker_store, init_photo_album, init_focus_store,
                 init_scene_store, init_device_store, init_node_store, init_usage_store,
                 init_push_tokens_store):
        init(mongo_db)
    start_mqtt_ingest()
    _initialized = True
    logger.debug("[Bootstrap] runtime initialized")


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


def _attachments_expiry(mongo_db) -> None:
    from app.features.attachments import ensure_expiry

    ensure_expiry(mongo_db)


def ensure_indexes() -> None:
    """Create every boot-time index independently (on the raw handle, before any tenant)."""
    from app.db import get_db

    mongo_db = get_db()
    if mongo_db is None:
        return

    # One failure must not skip the rest.
    index_jobs = [
        ("sandy_pending_state.updated_at_ttl", lambda: mongo_db.sandy_pending_state.create_index(
            "updated_at", expireAfterSeconds=60 * 60, background=True
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
        # Attachments are kept thirty days (older rows get thirty from the first boot).
        ("sandy_attachments.expire_at_ttl", lambda: _attachments_expiry(mongo_db)),
        # رموز إثبات الحضور للربط — خمس دقايق وبتروح لحالها.
        ("node_pair_challenges.expires_at_ttl",
         lambda: mongo_db.node_pair_challenges.create_index(
             "expires_at", expireAfterSeconds=0, background=True
         )),
        ("node_pair_challenges.node_tenant",
         lambda: mongo_db.node_pair_challenges.create_index(
             [("node_id", 1), ("tenant", 1)], unique=True, background=True
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

    # First, so the first failure is reported. No-op without SENTRY_DSN.
    try:
        from app.integrations.error_tracking import init_error_tracking

        init_error_tracking()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Bootstrap] error tracking failed to start: %s", exc)

    try:
        ensure_indexes()
    except Exception as exc:
        logger.warning("[Bootstrap] Mongo index setup failed: %s", exc)

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

        # sandy_schedules — reminders, scene reverts, nudges — once a minute.
        try:
            from app.blocks import init_blocks
            from app.db import get_db
            from app.services.schedule_runner import start_schedule_runner
            init_blocks(get_db())
            start_schedule_runner(get_db())
        except Exception as exc:
            logger.warning("[Bootstrap] schedule runner start failed: %s", exc)

    logger.debug("[Bootstrap] Startup complete (env=%s)", app_env)
