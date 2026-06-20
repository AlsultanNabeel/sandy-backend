"""Per-user usage metering + rate limits — MongoDB.

Cost control from day one: every authenticated request is counted per user per
day, and short bursts are throttled. Limits scale with subscription — the owner
is exempt (no rejection, still counted), a subscriber gets a generous quota, a
free user gets a modest one.

Collections:
  sandy_usage_daily  {_id: "<user_id>:<YYYY-MM-DD>", user_id, date, count, updated_at}
                     TTL on updated_at self-cleans old days.
  sandy_usage_rl     {_id: "<user_id>:<epoch_minute>", user_id, count, expire_at}
                     TTL on expire_at self-cleans the per-minute burst windows.

A limit value of 0 means "no limit" (used for the owner): the request is still
counted for analytics but never rejected. Fails open if Mongo is unavailable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

_DAILY = "sandy_usage_daily"
_RL = "sandy_usage_rl"
_mongo_db = None


def init_usage_store(mongo_db) -> None:
    """يُستدعى مرّة عند الإقلاع."""
    global _mongo_db
    _mongo_db = mongo_db
    if mongo_db is None:
        return
    try:
        mongo_db[_DAILY].create_index(
            "updated_at", expireAfterSeconds=60 * 60 * 24 * 40, background=True
        )
        mongo_db[_RL].create_index("expire_at", expireAfterSeconds=0, background=True)
        print("[UsageStore] ready")
    except Exception as e:  # noqa: BLE001
        print(f"[UsageStore] index skipped: {e}")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def requests_today(user_id: str) -> int:
    if _mongo_db is None or not user_id:
        return 0
    key = f"{user_id}:{_now():%Y-%m-%d}"
    doc = _mongo_db[_DAILY].find_one({"_id": key})
    return int((doc or {}).get("count", 0))


def check_and_record(user_id: str, *, daily_limit: int, per_min_limit: int) -> Optional[str]:
    """Count one request and return a rejection reason if the user is over a
    limit, else None. A limit of 0 disables that limit. Fails open on errors."""
    if _mongo_db is None or not user_id:
        return None
    from pymongo import ReturnDocument

    now = _now()
    # Per-minute burst window.
    try:
        rl_key = f"{user_id}:{int(now.timestamp() // 60)}"
        rl = _mongo_db[_RL].find_one_and_update(
            {"_id": rl_key},
            {"$inc": {"count": 1},
             "$setOnInsert": {"user_id": user_id, "expire_at": now + timedelta(seconds=120)}},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
        if per_min_limit and int((rl or {}).get("count", 0)) > per_min_limit:
            return "rate_limited"
    except Exception:  # noqa: BLE001
        pass
    # Daily quota.
    try:
        d_key = f"{user_id}:{now:%Y-%m-%d}"
        d = _mongo_db[_DAILY].find_one_and_update(
            {"_id": d_key},
            {"$inc": {"count": 1},
             "$set": {"updated_at": now},
             "$setOnInsert": {"user_id": user_id, "date": f"{now:%Y-%m-%d}"}},
            upsert=True, return_document=ReturnDocument.AFTER,
        )
        if daily_limit and int((d or {}).get("count", 0)) > daily_limit:
            return "daily_quota_exceeded"
    except Exception:  # noqa: BLE001
        pass
    return None
