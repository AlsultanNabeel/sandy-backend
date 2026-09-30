"""A held action across turns: its lifecycle, and where it waits (`sandy_pending_state`).

A delete or bulk change asks «متأكد؟» and waits for the next turn. The dict carries
``expires_at`` and ``consumed_at``; `live` is the only judge of whether it still holds.
The document id bakes in the tenant (``<chat_id>:<thread_id>``): ``thread_id`` is
client-supplied and may be guessable ("default"), so it can never be the only key.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import uuid4

from app.utils.time import USER_TZ

logger = logging.getLogger(__name__)

TTL_MINUTES = 10
_COLL = "sandy_pending_state"


def create(payload: Dict[str, Any]) -> Dict[str, Any]:
    now = datetime.now(USER_TZ)
    return {**payload, "created_at": now.isoformat(),
            "expires_at": (now + timedelta(minutes=TTL_MINUTES)).isoformat(),
            "nonce": uuid4().hex, "consumed_at": ""}


def live(pending: Optional[Dict[str, Any]]) -> bool:
    """Not consumed and not expired."""
    if not isinstance(pending, dict) or pending.get("consumed_at"):
        return False
    try:
        expires = datetime.fromisoformat(str(pending.get("expires_at") or "").replace("Z", "+00:00"))
    except ValueError:
        return False
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=USER_TZ)
    return expires > datetime.now(USER_TZ)


def _key(chat_id: str, thread_id: str) -> str:
    return f"{chat_id}:{thread_id}"


def load(thread_id: str, chat_id: str, mongo_db) -> Optional[Dict[str, Any]]:
    """The raw pending dict for this user's thread, or None."""
    if mongo_db is None or not thread_id or not chat_id:
        return None
    try:
        doc = mongo_db[_COLL].find_one({"_id": _key(chat_id, thread_id), "chat_id": chat_id})
        return doc.get("pending") if doc else None
    except Exception as exc:  # noqa: BLE001 — external call edge (Mongo)
        logger.warning("[pending] load failed: %s", exc)
        return None


def save(thread_id: str, chat_id: str, mongo_db, pending: Optional[Dict[str, Any]]) -> None:
    """Persist the turn's pending, or clear it when there is none."""
    if mongo_db is None or not thread_id or not chat_id:
        return
    try:
        key = _key(chat_id, thread_id)
        if not pending:
            mongo_db[_COLL].delete_one({"_id": key})
            return
        mongo_db[_COLL].update_one({"_id": key}, {"$set": {
            "chat_id": chat_id, "pending": pending,
            "updated_at": datetime.now(timezone.utc)}}, upsert=True)
    except Exception as exc:  # noqa: BLE001 — external call edge (Mongo)
        logger.warning("[pending] save failed: %s", exc)
