"""MongoDB connection setup."""

import logging
from typing import Any, Optional, Tuple

import certifi

from app.config import APP_ENV

logger = logging.getLogger(__name__)

# There is no second store to fall back to.
#
# Three of the log lines below used to end "using JSON memory for now" / "falling
# back to JSON memory". That store was removed: `app.db.configure(None)` leaves
# `get_db()` returning None, and every feature store guards on it and returns its
# empty default. So the fallback is not another database — it is Sandy running
# with no memory at all, answering reads with nothing and accepting writes that
# go nowhere, while `/health` is the only place that says so.
#
# On a laptop that is the right behaviour: the package imports and the tests run
# with no credentials, deliberately (§2.1). In production it is the worst kind of
# outage — the silent one — and it is exactly what C6 means by critical config
# failing fast at boot. Production is also what the robot on the desk is talking
# to (§1), so "up but knows nothing" is a robot that has forgotten its owner.
_NO_DB_IN_PROD = (
    "No database connection in prod. Refusing to start: the app would serve "
    "empty reads and silently discard every write. See the error above."
)

try:
    from pymongo import MongoClient

    MONGODB_AVAILABLE = True
except ImportError:
    MongoClient = None
    MONGODB_AVAILABLE = False
    logger.warning("[Warning] PyMongo not available. To enable: pip install pymongo>=4.6.0")


def _connect_mongo(uri: str) -> Any:
    """Build Mongo client with Atlas-friendly TLS defaults for cloud runtimes."""
    base_kwargs = {
        "serverSelectionTimeoutMS": 20000,
        "connectTimeoutMS": 20000,
        "socketTimeoutMS": 20000,
        "retryWrites": True,
        # Sized against the threads that actually contend for it, per worker:
        # 8 gunicorn threads + the 8-worker soul pool + the 10-worker
        # sandy_executor + the MQTT listener + the scheduler. At the old value
        # of 10 they queued for a connection under any real concurrency, and a
        # request that is waiting on the pool looks exactly like a slow query.
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
    """Initialize MongoDB connection and return (mongo_client, mongo_db)."""
    if not MONGODB_AVAILABLE:
        logger.error("[MongoDB] PyMongo is not installed")
        if APP_ENV == "prod":
            raise RuntimeError(_NO_DB_IN_PROD)
        logger.warning("[MongoDB] APP_ENV=%s — starting with no database", APP_ENV)
        return None, None

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
        # **There is no retry without certificate validation.**
        #
        # There used to be: any failure of the connect above — including an
        # actual interception — fell through to a client built with
        # `tlsAllowInvalidCertificates=True`, and the only trace was a warning
        # nobody reads. Every message, every memory and every voiceprint then
        # travelled over a connection that would accept a forged certificate.
        #
        # The first attempt already pins `certifi`, so a genuine CA problem is
        # fixed there. A database that will not connect is a loud outage; a
        # database that connects insecurely is a quiet one.
        logger.error("[MongoDB] connection failed: %s", connect_error)
        logger.error(
            "[MongoDB] Hint: check Atlas Network Access allowlist and URI credentials"
        )
        if APP_ENV == "prod":
            # Crash the worker. Heroku restarts it, which is the retry — and a
            # dyno that will not come up is a page. A dyno that came up without
            # a database is a week of "Sandy forgot everything I told her".
            raise RuntimeError(_NO_DB_IN_PROD) from connect_error
        logger.warning("[MongoDB] APP_ENV=%s — starting with no database", APP_ENV)
        return None, None
