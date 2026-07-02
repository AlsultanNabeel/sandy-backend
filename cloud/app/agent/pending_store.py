"""Per-conversation pending-action persistence.

The graph pipeline threads ``pending_state`` through a single turn (see
``app/agent/pending.py`` for its create/validate/consume lifecycle) but never
persisted it across HTTP requests — a tool asking "متأكد؟" had its pending
discarded the moment the response went out, so the next turn's "اه" had no
context and routed as plain chat. This module is the missing piece: load
before the turn, save after.

Scoped by the same thread_id ``run_graph`` itself uses (conversation_id or
chat_id), so a pending never leaks across conversations or users. Validity
(expiry/consumed) is still governed entirely by ``app/agent/pending.py`` —
this module only stores and returns the raw dict.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_COLL = "sandy_pending_state"


def load_pending_state(thread_id: str, mongo_db) -> Optional[Dict[str, Any]]:
    """Return the raw pending dict for this thread, or None."""
    if mongo_db is None or not thread_id:
        return None
    try:
        doc = mongo_db[_COLL].find_one({"_id": thread_id})
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
    if mongo_db is None or not thread_id:
        return
    try:
        if not pending:
            mongo_db[_COLL].delete_one({"_id": thread_id})
            return
        mongo_db[_COLL].update_one(
            {"_id": thread_id},
            {"$set": {
                "chat_id": chat_id,
                "pending": pending,
                "updated_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception as exc:
        logger.warning(f"[pending_store] save failed: {exc}")
