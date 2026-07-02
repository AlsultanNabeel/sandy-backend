"""Persistent memory: one per-tenant doc in the ``memory`` MongoDB collection.

Used to be a single global ``sandy_memory`` doc shared by everyone, gated to the
owner only. Closed for Phase 4 ("close the globals") via the same enforced
``ScopedCollection`` boundary every other store uses (``app.utils.tenant_db``) —
each authenticated user gets their own doc, stamped and filtered by tenant id
automatically, so no code path can read or write another tenant's memory.

The pre-isolation legacy doc (and any doc still tagged with one of the owner's
old identities) is reconciled onto his canonical tenant id by
``app.utils.user_profiles.reconcile_owner_identity``, called once at boot.
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional

from app.utils.tenant_db import scoped

logger = logging.getLogger(__name__)

_COLLECTION = "memory"


def _default_memory() -> Dict[str, Any]:
    now = datetime.now().isoformat()
    return {
        "conversations": [],
        "facts": [],
        "reminders": [],
        "tasks": [],
        "sandy_state": {
            "mood": "happy",
            "last_user_message_time": now,
            "repeat_count": 0,
            "last_message": "",
            "snapped": False,
            "last_mood_change": now,
            "custom_facts": [],
            "user_persona_profile": "",
            "persona_profile": "",
            "home_city": "October City",
            "last_briefing_date": "",
            "context_summary": "",
            "last_synthesized": "",
            "predicted_intent": "",
        },
    }


def load_memory(mongo_db: Optional[Any] = None) -> Dict[str, Any]:
    """Load the current tenant's memory doc, or an empty default (no tenant,
    no MongoDB, or nothing saved yet)."""
    default_memory = _default_memory()
    coll = scoped(mongo_db, _COLLECTION)
    if coll is None:
        return default_memory
    try:
        doc = coll.find_one({})
        if doc:
            doc.pop("_id", None)
            doc.pop("user_id", None)
            return doc
    except Exception as e:
        logger.warning("[Memory] MongoDB load error: %s", e)
    return default_memory


def save_memory(memory: Dict[str, Any], mongo_db: Optional[Any] = None) -> None:
    """Save the current tenant's memory doc. No-op with no tenant/no MongoDB."""
    coll = scoped(mongo_db, _COLLECTION)
    if coll is None:
        return
    doc = dict(memory)
    # Cap the chat log so a single doc can't approach the 16MB BSON limit. Keep
    # the most recent entries; don't mutate the caller's dict.
    convos = doc.get("conversations")
    if isinstance(convos, list) and len(convos) > 500:
        doc["conversations"] = convos[-500:]
    try:
        coll.replace_one({}, doc, upsert=True)
    except Exception as e:
        logger.warning("[Memory] MongoDB save error: %s", e)
