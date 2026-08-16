"""Device push tokens — the address book for remote notifications (Phase 7).

Every install that grants notification permission POSTs its APNs device token to
``/api/push/register``; we keep the token → user_id mapping so the daily-nudge
scheduler knows where to deliver each user's morning line.

A token is globally unique to one device, so it IS the ``_id``: re-registering
the same token just refreshes its owner + timestamp (a device can be handed to a
new account). Tokens that APNs later reports as gone (410 / BadDeviceToken) are
pruned by the sender.

Collection: sandy_push_tokens
  {_id: device_token, user_id, platform ("ios"), created_at, updated_at}

Infra, not per-tenant user data: keyed by the physical token and stamped with
its owner, so it is intentionally NOT a scoped() collection.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List
from app.db import configure, get_db

logger = logging.getLogger(__name__)

_COLL = "sandy_push_tokens"


def init_push_tokens_store(mongo_db) -> None:
    """Called once at boot (same pattern as the other stores)."""
    configure(mongo_db)
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index("user_id", background=True)
        logger.info("[PushTokens] ready")
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PushTokens] index skipped: %s", exc)


def _coll():
    return get_db()[_COLL] if get_db() is not None else None


def register_token(user_id: str, token: str, platform: str = "ios") -> bool:
    """Bind a device token to a user (upsert; the token is the key)."""
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


def unregister_token(token: str) -> bool:
    """Drop a token (on logout, or when APNs reports it gone)."""
    coll = _coll()
    token = (token or "").strip()
    if coll is None or not token:
        return False
    try:
        coll.delete_one({"_id": token})
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PushTokens] unregister failed: %s", exc)
        return False


# أجهزة الشخص الواحد. رقم كبير ع الواقع — عشان يمسك خلل بالتسجيل، مش يحدّ حدا.
MAX_TOKENS_PER_USER = 50


def tokens_for_user(user_id: str) -> List[str]:
    """All device tokens currently registered to a user."""
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
    """Distinct users who have at least one device registered (scheduler fan-out)."""
    coll = _coll()
    if coll is None:
        return []
    try:
        return [u for u in coll.distinct("user_id") if u]
    except Exception as exc:  # noqa: BLE001
        logger.warning("[PushTokens] distinct users failed: %s", exc)
        return []
