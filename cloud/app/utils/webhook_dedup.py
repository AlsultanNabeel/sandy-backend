"""Cross-process Telegram webhook dedup — MongoDB setnx with TTL.

Extracted from the old ``project_builder/_redis.py`` (a general Mongo KV store
that was misfiled under the now-removed self-coding package). ``webhook_seen_setnx``
was the only general-purpose piece the web/Telegram path used from it.

Collection: sandy_sa_kv  ({_id: namespaced key, value, expire_at}). A TTL index
on ``expire_at`` self-cleans entries; the function also drops a stale key on touch.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

logger = logging.getLogger(__name__)

_COLL = "sandy_sa_kv"
_ttl_ensured = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _coll():
    try:
        from app.agent.facade.agent import mongo_db
    except Exception as exc:  # noqa: BLE001
        logger.debug("[webhook_dedup] mongo unavailable: %s", exc)
        return None
    if mongo_db is None:
        return None
    coll = mongo_db[_COLL]
    global _ttl_ensured
    if not _ttl_ensured:
        try:
            coll.create_index("expire_at", expireAfterSeconds=0, background=True)
        except Exception:  # noqa: BLE001
            pass
        _ttl_ensured = True
    return coll


def webhook_seen_setnx(run_id: Any, ttl: int = 3600) -> bool:
    """True if this run_id is new (and reserves it), False if already seen."""
    coll = _coll()
    if coll is None:
        return True  # fail-open
    key = f"sandy_sa:webhook_seen:{run_id}"
    now = _now()
    try:
        from pymongo.errors import DuplicateKeyError
        coll.delete_one({"_id": key, "expire_at": {"$lte": now}})
        try:
            coll.insert_one({"_id": key, "value": "1",
                             "expire_at": now + timedelta(seconds=ttl)})
            return True
        except DuplicateKeyError:
            return False
    except Exception:  # noqa: BLE001
        return True
