"""Guest rate limiting: per-resource usage tracking with a Telegram approval flow.

Each guest JWT (keyed by JTI) gets a usage doc per resource type. When the
count hits the limit, the owner gets a Telegram message with inline
approve/reject buttons. Approve adds more uses; reject blocks further use.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

logger = logging.getLogger(__name__)

_COLLECTION = "guest_usage"
_DEFAULT_LIMIT = 3
# Cap how many daily reminders we send the owner about one pending guest, so a
# long-pending request can't ping forever.
_MAX_REPINGS = 3
# "all" is the shared budget: chat, search, voice and images draw from one
# counter per guest, so a guest gets `_DEFAULT_LIMIT` messages across everything.
_CHAT_TYPES = frozenset({"all", "image", "search", "chat"})


def guest_label(jti: str) -> str:
    """User-friendly label from JTI: 'Guest #A92K'"""
    h = hashlib.sha1(jti.encode(), usedforsecurity=False).hexdigest().upper()
    return f"Guest #{h[:4]}"


def detect_chat_type(message: str) -> str:
    """Infer resource type from message content (chat vs search)."""
    m = message.strip()
    if any(m.startswith(p) for p in ("ابحث", "ابحثي", "search", "بحث عن")):
        return "search"
    return "chat"


def check_and_increment(
    jti: str,
    name: str,
    chat_type: str,
    mongo_db,
) -> Tuple[str, int, int]:
    """
    Consume one usage for (jti, chat_type) and return status.

    The budget is finite: a guest gets `limit` uses. `count` goes up only
    on an allowed use, never while pending or blocked, so the count/limit
    math stays exact. When the budget runs out the owner is asked; an
    approval grants `boost` more uses (limit += boost) and then the owner is
    asked again. There is no "approved means unlimited" shortcut.

    Returns:
        (status, count, limit)
        status: "allow" | "block" | "pending"
    """
    if mongo_db is None or chat_type not in _CHAT_TYPES:
        return "allow", 0, _DEFAULT_LIMIT

    try:
        now = datetime.now(timezone.utc)
        col = mongo_db[_COLLECTION]
        doc = col.find_one({"jti": jti, "chat_type": chat_type})

        # First use ever → create doc and allow.
        if doc is None:
            col.insert_one({
                "jti": jti,
                "chat_type": chat_type,
                "name": name or guest_label(jti),
                "count": 1,
                "limit": _DEFAULT_LIMIT,
                "approval_state": "none",
                "created_at": now,
                "last_request_at": now,
            })
            return "allow", 1, _DEFAULT_LIMIT

        count = doc.get("count", 0)
        limit = doc.get("limit", _DEFAULT_LIMIT)
        state = doc.get("approval_state", "none")

        if state == "rejected":
            return "block", count, limit

        # Still within the granted budget → consume one use.
        if count < limit:
            col.update_one(
                {"jti": jti, "chat_type": chat_type},
                {"$inc": {"count": 1}, "$set": {"last_request_at": now}},
            )
            return "allow", count + 1, limit

        # Budget used up (count >= limit), so don't consume.
        if state == "pending":
            # Already waiting. Re-ping the owner only if it's been >24h since
            # the last notification (a reminder, not spam). Guest polling for
            # status goes through a separate read-only endpoint, so it does
            # not reset this timer.
            notified_at = doc.get("notified_at") or doc.get("last_request_at")
            if notified_at is not None:
                if notified_at.tzinfo is None:
                    notified_at = notified_at.replace(tzinfo=timezone.utc)
                reping_count = int(doc.get("reping_count") or 0)
                if (now - notified_at).total_seconds() > 86_400 and reping_count < _MAX_REPINGS:
                    col.update_one(
                        {"jti": jti, "chat_type": chat_type},
                        {"$set": {"notified_at": now}, "$inc": {"reping_count": 1}},
                    )
                    _notify_owner(jti, name, chat_type, count, limit)
            return "pending", count, limit

        # state in ("none", "approved") and budget used up → ask for more.
        col.update_one(
            {"jti": jti, "chat_type": chat_type},
            {"$set": {"approval_state": "pending", "notified_at": now,
                      "last_request_at": now}},
        )
        _notify_owner(jti, name, chat_type, count, limit)
        return "pending", count, limit

    except Exception as exc:
        logger.debug("[guest_usage] check_and_increment failed: %s", exc)
        return "allow", 0, _DEFAULT_LIMIT


def approve_guest(jti: str, chat_type: str, boost: int, mongo_db) -> bool:
    """Grant `boost` more uses, measured from the current count.

    Setting ``limit = count + boost`` (not ``limit += boost``) keeps the grant
    correct whatever the current count is, including legacy docs whose count
    was inflated before the finite-budget fix. Otherwise, if the count already
    passed the old limit, the next message would still be over budget and the
    owner would get pinged again right after approving.
    """
    if mongo_db is None:
        return False
    try:
        col = mongo_db[_COLLECTION]
        doc = col.find_one({"jti": jti, "chat_type": chat_type})
        current = (doc or {}).get("count", 0)
        new_limit = current + max(1, int(boost))
        col.update_one(
            {"jti": jti, "chat_type": chat_type},
            {"$set": {"limit": new_limit, "approval_state": "approved",
                      "notified_at": None}},
        )
        return True
    except Exception as exc:
        logger.debug("[guest_usage] approve failed: %s", exc)
        return False


def reject_guest(jti: str, chat_type: str, mongo_db) -> bool:
    """Block all further requests for this (jti, chat_type)."""
    if mongo_db is None:
        return False
    try:
        mongo_db[_COLLECTION].update_one(
            {"jti": jti, "chat_type": chat_type},
            {"$set": {"approval_state": "rejected"}},
        )
        return True
    except Exception as exc:
        logger.debug("[guest_usage] reject failed: %s", exc)
        return False


def get_usage_doc(jti: str, chat_type: str, mongo_db) -> Optional[dict]:
    """Return the raw usage doc for auditing."""
    if mongo_db is None:
        return None
    try:
        return mongo_db[_COLLECTION].find_one(
            {"jti": jti, "chat_type": chat_type}, {"_id": 0}
        )
    except Exception:
        return None


def _notify_owner(jti: str, name: str, chat_type: str, count: int, limit: int) -> None:
    """Owner notification for a guest's access request.

    Telegram was removed in the product migration; the request is still recorded
    as ``pending`` on the usage doc by the caller. Delivering the notification
    (and the approve/extend action) moves to in-app push in a later phase, so
    this is intentionally a no-op for now.
    """
    return
