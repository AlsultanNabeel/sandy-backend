"""MongoDB connection setup."""

import logging
from typing import Any, Optional, Tuple

import certifi
from pymongo import MongoClient

from app.config import APP_ENV

logger = logging.getLogger(__name__)

# Without a db every store returns empty defaults. Fine locally; in prod refuse to boot.
_NO_DB_IN_PROD = (
    "No database connection in prod. Refusing to start: the app would serve "
    "empty reads and silently discard every write. See the error above."
)


def _connect_mongo(uri: str) -> Any:
    base_kwargs = {
        "serverSelectionTimeoutMS": 20000,
        "connectTimeoutMS": 20000,
        "socketTimeoutMS": 20000,
        "retryWrites": True,
        # Per worker: 8 gunicorn threads + 8 soul pool + 10 executor + MQTT + scheduler.
        "maxPoolSize": 50,
        "minPoolSize": 1,
        "appname": "sandy-heroku-agent",
    }
    client = MongoClient(uri, tls=True, tlsCAFile=certifi.where(), **base_kwargs)
    client.admin.command("ping")
    return client


def init_mongo_connection(
    mongodb_uri: str, mongodb_db_name: str
) -> Tuple[Optional[Any], Optional[Any]]:
    """(mongo_client, mongo_db), or (None, None) outside prod."""
    if not mongodb_uri:
        logger.error("[MongoDB] MONGODB_URI is not set")
        if APP_ENV == "prod":
            raise RuntimeError(_NO_DB_IN_PROD)
        logger.warning("[MongoDB] APP_ENV=%s — starting with no database", APP_ENV)
        return None, None

    try:
        mongo_client = _connect_mongo(mongodb_uri)
        mongo_db = mongo_client[mongodb_db_name]
        logger.info("[MongoDB] connected (db=%s)", mongodb_db_name)
        return mongo_client, mongo_db

    except Exception as connect_error:
        # Never retry without certificate validation.
        logger.error("[MongoDB] connection failed: %s", connect_error)
        logger.error(
            "[MongoDB] Hint: check Atlas Network Access allowlist and URI credentials"
        )
        if APP_ENV == "prod":
            # Crash the worker; Heroku's restart is the retry.
            raise RuntimeError(_NO_DB_IN_PROD) from connect_error
        logger.warning("[MongoDB] APP_ENV=%s — starting with no database", APP_ENV)
        return None, None
