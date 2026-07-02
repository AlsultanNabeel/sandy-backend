"""Persistent memory management: load/save to MongoDB or disk JSON."""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from app.utils.files import read_json_file, write_json_file
# NOTE: this module is the legacy GLOBAL memory/session ("sandy_memory" /
# "current_session" — one doc for everyone), not per-user. It stays scoped to
# the owner tenant transitionally; Phase 4 ("close the globals") makes it
# per-tenant. Gating on the owner id keeps other users out of his global state.
from app.utils.user_profiles import current_user_id, is_owner_chat_id


def _is_owner_context() -> bool:
    return is_owner_chat_id(current_user_id())

logger = logging.getLogger(__name__)

# Defaults


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


# Load and save (sync)


def load_memory(
    memory_file: Optional[Path] = None, mongo_db: Optional[Any] = None
) -> Dict[str, Any]:
    """Load persistent memory from MongoDB (preferred) or disk JSON."""
    default_memory = _default_memory()

    if not _is_owner_context():
        return default_memory

    if mongo_db is not None:
        try:
            memory_doc = mongo_db["memory"].find_one({"_id": "sandy_memory"})
            if memory_doc:
                memory_doc.pop("_id", None)
                logger.info("[Memory] loaded from MongoDB")
                return memory_doc

            json_memory = read_json_file(memory_file, None)
            if isinstance(json_memory, dict):
                mongo_db["memory"].replace_one(
                    {"_id": "sandy_memory"},
                    {**json_memory, "_id": "sandy_memory"},
                    upsert=True,
                )
                logger.info("[Memory] migrated JSON to MongoDB")
                return json_memory

            logger.info("[Memory] MongoDB is source of truth (new memory)")
            return default_memory

        except Exception as e:
            logger.warning(f"[Memory] MongoDB error: {e}, falling back to JSON")

    memory_json = read_json_file(memory_file, None)
    if isinstance(memory_json, dict):
        logger.info("[Memory] loaded from JSON file")
        return memory_json

    return default_memory


def save_memory(
    memory: Dict[str, Any],
    memory_file: Optional[Path] = None,
    mongo_db: Optional[Any] = None,
) -> None:
    """Save persistent memory to MongoDB (preferred) or disk JSON."""
    if not _is_owner_context():
        return

    if mongo_db is not None:
        try:
            doc = {**memory, "_id": "sandy_memory"}
            # Cap the chat log so the single doc can't approach the 16MB BSON
            # limit. Keep the most recent entries; build a new list so the
            # caller's memory dict isn't mutated.
            convos = doc.get("conversations")
            if isinstance(convos, list) and len(convos) > 500:
                doc["conversations"] = convos[-500:]
            mongo_db["memory"].replace_one(
                {"_id": "sandy_memory"},
                doc,
                upsert=True,
            )
            return
        except Exception as e:
            logger.warning(f"[Memory] MongoDB save error: {e}, falling back to JSON")

    if write_json_file(memory_file, memory):
        logger.info("[Memory] saved to JSON file")


