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
        with open(key_path, "w") as f:
            f.write(creds_json)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(key_path)
        logger.debug("[Bootstrap] Google credentials written to %s", key_path)
    except Exception as exc:
        logger.warning("[Bootstrap] Failed to write Google credentials: %s", exc)


def ensure_data_dirs() -> None:
    """Create runtime data directories if they don't exist."""
    from app.config import MEMORY_DIR, TASKS_DIR

    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    logger.debug("[Bootstrap] Data directories ready")


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


    try:
        from app.agent.tools.setup import register_all_tools

        register_all_tools()
    except Exception as exc:
        logger.warning("[Bootstrap] Tools registration failed: %s", exc)

    try:
        from app.agent.facade.agent import mongo_db
        from app.agent.health_monitor import ensure_ttl_index
        try:
            ensure_ttl_index(mongo_db)
        except Exception as exc:
            logger.warning("[Bootstrap] ensure_ttl_index failed: %s", exc)
        if mongo_db is not None:
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
            ]
            for label, job in index_jobs:
                try:
                    job()
                except Exception as exc:
                    logger.warning("[Bootstrap] create_index %s failed: %s", label, exc)
    except Exception as exc:
        logger.warning("[Bootstrap] Mongo index setup failed: %s", exc)

    logger.debug("[Bootstrap] Startup complete (env=%s)", app_env)
