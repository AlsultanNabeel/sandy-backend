"""APNs device tokens → user_id, for the daily-nudge scheduler.

The token is the ``_id`` (re-registering refreshes its owner). Infrastructure,
keyed by the physical token, so intentionally not a scoped() collection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List
from app.db import configure, get_db

logger = logging.getLogger(__name__)

_COLL = "sandy_push_tokens"


def init_push_tokens_store(mongo_db) -> None:
    configure(mongo_db)
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index("user_id", background=True)
        logger.info("[PushTokens] ready")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PushTokens] index skipped: %s", exc)


def _coll():
    # Kept in this exact shape: tests/test_tenant_scoping_guard.py looks for it.
    return get_db()[_COLL] if get_db() is not None else None


def register_token(user_id: str, token: str, platform: str = "ios") -> bool:
    coll = _coll()
    token = (token or "").strip()
    if coll is None or not user_id or not token:
        return False
    now = datetime.now(timezone.utc)
    try:
        coll.update_one(
            {"_id": token},
            {"$set": {"user_id": str(user_id), "platform": (platform or "ios").strip()[:20],
                      "updated_at": now},
             "$setOnInsert": {"created_at": now}},
            upsert=True,
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PushTokens] register failed: %s", exc)
        return False


def unregister_token(token: str, user_id: str | None = None) -> bool:
    """Drop a token. With ``user_id``, only if that caller owns it; APNs pruning passes none."""
    coll = _coll()
    token = (token or "").strip()
    if coll is None or not token:
        return False
    query = {"_id": token}
    if user_id is not None:
        if not user_id:
            return False
        query["user_id"] = str(user_id)
    try:
        coll.delete_one(query)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PushTokens] unregister failed: %s", exc)
        return False


# سقف أمان لأجهزة الشخص الواحد.
MAX_TOKENS_PER_USER = 50


def tokens_for_user(user_id: str) -> List[str]:
    coll = _coll()
    if coll is None or not user_id:
        return []
    try:
        return [d["_id"] for d in
                coll.find({"user_id": str(user_id)}, {"_id": 1}).limit(MAX_TOKENS_PER_USER)]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PushTokens] tokens_for_user failed: %s", exc)
        return []


def user_ids_with_tokens() -> List[str]:
    coll = _coll()
    if coll is None:
        return []
    try:
        return [u for u in coll.distinct("user_id") if u]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PushTokens] distinct users failed: %s", exc)
        return []
