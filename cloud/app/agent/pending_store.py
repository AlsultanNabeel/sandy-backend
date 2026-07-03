"""Per-conversation pending-action persistence.

The graph pipeline threads ``pending_state`` through a single turn (see
``app/agent/pending.py`` for its create/validate/consume lifecycle) but never
persisted it across HTTP requests — a tool asking "متأكد؟" had its pending
discarded the moment the response went out, so the next turn's "اه" had no
context and routed as plain chat. This module is the missing piece: load
before the turn, save after.

Keyed by a composite ``<chat_id>:<thread_id>`` so a pending can never leak or
collide across users — the ``conversation_id`` half of ``thread_id`` is
client-supplied and could be a shared/guessable value (e.g. "default"), so the
tenant id must be baked into the document id itself, not trusted from the client.
Validity (expiry/consumed) is still governed entirely by ``app/agent/pending.py``
— this module only stores and returns the raw dict.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_COLL = "sandy_pending_state"


def _key(chat_id: str, thread_id: str) -> str:
    """Tenant-scoped document id. Two users sharing a conversation_id (even a
    guessable one like "default") get different documents, so neither can read
    nor overwrite the other's pending action."""
    return f"{chat_id}:{thread_id}"


def load_pending_state(thread_id: str, chat_id: str, mongo_db) -> Optional[Dict[str, Any]]:
    """Return the raw pending dict for THIS user's thread, or None."""
    if mongo_db is None or not thread_id or not chat_id:
        return None
    try:
        doc = mongo_db[_COLL].find_one({"_id": _key(chat_id, thread_id), "chat_id": chat_id})
        return doc.get("pending") if doc else None
    except Exception as exc:
        logger.warning(f"[pending_store] load failed: {exc}")
        return None


def save_pending_state(
    thread_id: str,
    chat_id: str,
    mongo_db,
    pending: Optional[Dict[str, Any]],
) -> None:
    """Persist the turn's pending_state, or clear it when falsy/consumed."""
    if mongo_db is None or not thread_id or not chat_id:
        return
    try:
        key = _key(chat_id, thread_id)
        if not pending:
            mongo_db[_COLL].delete_one({"_id": key})
            return
        mongo_db[_COLL].update_one(
            {"_id": key},
            {"$set": {
                "chat_id": chat_id,
                "pending": pending,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception as exc:
        logger.warning(f"[pending_store] save failed: {exc}")
