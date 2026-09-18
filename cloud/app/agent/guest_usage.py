"""Guest rate limiting: per-resource usage tracking.

Each guest JWT (keyed by JTI) gets a usage doc per resource type. When the count
hits the limit the guest is refused, and the request is marked ``pending`` on
that doc.

Read the word "pending" carefully: nothing acts on it. The approval channel it
was written for ran over Telegram and left with it, and the in-app replacement
is not built. So a guest who hits the limit stays refused, and the pending mark
is a record that they asked — not a request waiting in anyone's queue.

That is written here rather than left for the next reader to work out, because
the original docstring described approve/reject buttons that had not existed for
months, and a docstring describing a feature that is gone is worse than no
docstring: it is believed.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

_COLLECTION = "guest_usage"
_DEFAULT_LIMIT = 3
# "all" is the shared budget: chat, search, voice and images draw from one
# counter per guest, so a guest gets `_DEFAULT_LIMIT` messages across everything.
_CHAT_TYPES = frozenset({"all", "image", "search", "chat"})


def guest_label(jti: str) -> str:
    """User-friendly label from JTI: 'Guest #A92K'"""
    h = hashlib.sha1(jti.encode(), usedforsecurity=False).hexdigest().upper()
    return f"Guest #{h[:4]}"


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
    math stays exact. When the budget runs out the doc is marked ``pending``
    (see the module docstring: nothing approves it today). ``rejected`` is
    still honoured for docs that carry it from the Telegram era.

    A database error refuses the guest (``block``): guest traffic is the
    unauthenticated, uncapped-cost path, so it fails closed.

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

        # First use ever → create doc and allow. Two first requests can race
        # here; the unique (jti, chat_type) index makes the loser raise, and it
        # is then simply a second use of the doc the winner created.
        if doc is None:
            try:
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
            except DuplicateKeyError:
                doc = col.find_one({"jti": jti, "chat_type": chat_type}) or {}

        count = doc.get("count", 0)
        limit = doc.get("limit", _DEFAULT_LIMIT)
        state = doc.get("approval_state", "none")

        if state == "rejected":
            return "block", count, limit

        # Still within the granted budget → consume one use ATOMICALLY. The
        # count==count guard means only one of N concurrent requests wins the
        # increment, so a guest can't slip past the limit with a burst (the
        # read-then-write TOCTOU race). The loser falls through to the pending
        # path below (asked at most one use early — harmless).
        if count < limit:
            from pymongo import ReturnDocument
            updated = col.find_one_and_update(
                {"jti": jti, "chat_type": chat_type, "count": count},
                {"$inc": {"count": 1}, "$set": {"last_request_at": now}},
                return_document=ReturnDocument.AFTER,
            )
            if updated is not None:
                return "allow", updated.get("count", count + 1), limit
            doc = col.find_one({"jti": jti, "chat_type": chat_type}) or doc
            count = doc.get("count", count)
            limit = doc.get("limit", limit)
            state = doc.get("approval_state", state)
            if state == "rejected":
                return "block", count, limit

        # Budget used up (count >= limit), so don't consume.
        if state != "pending":
            col.update_one(
                {"jti": jti, "chat_type": chat_type},
                {"$set": {"approval_state": "pending", "last_request_at": now}},
            )
        return "pending", count, limit

    except Exception as exc:
        logger.warning("[guest_usage] check_and_increment failed: %s", exc)
        return "block", 0, _DEFAULT_LIMIT


def get_usage_doc(jti: str, chat_type: str, mongo_db) -> Optional[dict]:
    """Return the raw usage doc for auditing."""
    if mongo_db is None:
        return None
    try:
        return mongo_db[_COLLECTION].find_one(
            {"jti": jti, "chat_type": chat_type}, {"_id": 0}
        )
    except Exception as exc:
        logger.warning("[guest_usage] read failed: %s", exc)
        return None

