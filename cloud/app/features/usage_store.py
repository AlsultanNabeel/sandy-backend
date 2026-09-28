"""Per-user usage metering and rate limits.

sandy_usage_daily counts requests per user per day; sandy_usage_rl holds
per-minute burst windows. Both self-clean via TTL. A limit of 0 means
"count but never reject" (the owner). Fails open if Mongo is unavailable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.db import configure, get_db

logger = logging.getLogger(__name__)

_DAILY = "sandy_usage_daily"
_RL = "sandy_usage_rl"


def init_usage_store(mongo_db) -> None:
    configure(mongo_db)
    if mongo_db is None:
        return
    try:
        mongo_db[_DAILY].create_index(
            "updated_at", expireAfterSeconds=60 * 60 * 24 * 40, background=True
        )
        mongo_db[_RL].create_index("expire_at", expireAfterSeconds=0, background=True)
        logger.info("[UsageStore] ready")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[UsageStore] index skipped: {e}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def check_and_record(user_id: str, *, daily_limit: int, per_min_limit: int) -> Optional[str]:
    """Count one request; a rejection reason if over a limit, else None (fails open)."""
    if get_db() is None or not user_id:
        return None
    from pymongo import ReturnDocument

    now = _now()
    # Per-minute burst window.
    try:
        rl_key = f"{user_id}:{int(now.timestamp() // 60)}"
        rl = get_db()[_RL].find_one_and_update(
            {"_id": rl_key},
            {"$inc": {"count": 1},
             "$setOnInsert": {"user_id": user_id, "expire_at": now + timedelta(seconds=120)}},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
        if per_min_limit and int((rl or {}).get("count", 0)) > per_min_limit:
            return "rate_limited"
    except Exception:  # noqa: BLE001
        logger.debug("ignoring non-critical error", exc_info=True)
    # Daily quota.
    try:
        d_key = f"{user_id}:{now:%Y-%m-%d}"
        d = get_db()[_DAILY].find_one_and_update(
            {"_id": d_key},
            {"$inc": {"count": 1},
             "$set": {"updated_at": now},
             "$setOnInsert": {"user_id": user_id, "date": f"{now:%Y-%m-%d}"}},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
        if daily_limit and int((d or {}).get("count", 0)) > daily_limit:
            return "daily_quota_exceeded"
    except Exception:  # noqa: BLE001
        logger.debug("ignoring non-critical error", exc_info=True)
    return None
