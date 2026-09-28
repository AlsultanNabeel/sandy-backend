"""Erase a person completely (Apple requires in-app account deletion).

The collection list is written out on purpose: a new collection must be added
here, or its data survives deletion.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

# Deleted by `$or` on user_id and chat_id: some stores scope on chat_id.
_BY_USER: List[str] = [
    "sandy_nodes",
    "sandy_devices",
    "sandy_tasks",
    "sandy_reminders",
    "sandy_shopping",
    "sandy_habits",
    "sandy_expenses",
    "sandy_journal",
    "sandy_reading",
    "sandy_focus",
    "sandy_scenes",
    "sandy_scene_timers",
    "sandy_goals",
    "sandy_brainstorms",
    "sandy_memories",
    "sandy_voiceprints",
    "sandy_push_tokens",
    "sandy_future_messages",
    "sandy_shared_content",
    "sandy_daily_nudge",
    "sandy_session_state",
    "sandy_pending_state",
    "sandy_activity",
    "sandy_usage",
    "memory",
    "sandy_facts",
    "sandy_conversations",
    "sandy_context_metadata",
    "sandy_vector_index",
    "sandy_books",
    "sandy_reading_sessions",
    "sandy_reading_meta",
    "sandy_habit_log",
    "sandy_focus_meta",
    "sandy_photos",
    "sandy_gifts",
    "sandy_bs_pending",
    "sandy_evals",
    "sandy_state",
    "sandy_nudge_locks",
    "sandy_usage_daily",
    "sandy_usage_rl",
    "sandy_active_user_profile",
    # Cached voice prompt: holds the user's name and lists verbatim.
    "sandy_prompt_cache",
    # Chat threads (no `sandy_` prefix).
    "conversations",
]

# STM docs are keyed "<thread>:<user>" and also carry user_id; both are cleared.
_STM = "sandy_stm"


def _id_forms(user_id: str) -> List[Any]:
    """Every type this id appears in; legacy docs store the owner's id as an int."""
    forms: List[Any] = [user_id]
    if user_id.isdigit():
        forms.append(int(user_id))
    return forms


# GridFS photo bytes have no user field; removed via each sandy_photos row's grid_id.
_PHOTO_BUCKET = "sandy_photo_files"


def _erase_photo_blobs(db, forms: List[Any]) -> int:
    """Delete this user's GridFS photo files (chunks first); returns how many."""
    # بلا سقف: a capped read would leave photos behind.
    ids = [row["grid_id"] for row in db["sandy_photos"].find(
        {"$or": [{"user_id": {"$in": forms}}, {"chat_id": {"$in": forms}}]},
        {"grid_id": 1}) if row.get("grid_id") is not None]
    if not ids:
        return 0
    db[f"{_PHOTO_BUCKET}.chunks"].delete_many({"files_id": {"$in": ids}})
    return db[f"{_PHOTO_BUCKET}.files"].delete_many({"_id": {"$in": ids}}).deleted_count


def _erase(user_id: str, names: List[str]) -> Dict[str, Any]:
    """Clear `names` plus STM for one user. Shared by wipe and delete so they can't drift."""
    from app.db import get_db

    user_id = (user_id or "").strip()
    if not user_id:
        return {"ok": False, "error": "no_user"}
    db = get_db()
    if db is None:
        return {"ok": False, "error": "no_store"}

    forms = _id_forms(user_id)
    removed: Dict[str, int] = {}
    if "sandy_photos" in names:
        try:
            n = _erase_photo_blobs(db, forms)
            if n:
                removed[_PHOTO_BUCKET] = n
        except PyMongoError as exc:
            logger.warning("[erase] photo files failed for %s: %s", user_id, exc)
            removed[_PHOTO_BUCKET] = -1
    for name in names:
        try:
            r = db[name].delete_many(
                {"$or": [{"user_id": {"$in": forms}},
                         {"chat_id": {"$in": forms}}]})
            if r.deleted_count:
                removed[name] = r.deleted_count
        except PyMongoError as exc:
            logger.warning("[erase] %s failed for %s: %s", name, user_id, exc)
            removed[name] = -1

    try:
        r = db[_STM].delete_many({"user_id": {"$in": forms}})
        n = r.deleted_count
        r2 = db[_STM].delete_many(
            {"key": {"$regex": f":{re.escape(user_id)}$"}})
        n += r2.deleted_count
        if n:
            removed[_STM] = n
    except PyMongoError as exc:
        logger.warning("[erase] stm failed for %s: %s", user_id, exc)
        removed[_STM] = -1

    # Web chat transcript is keyed by `_id` only.
    try:
        r = db["web_chat_history"].delete_one({"_id": f"web_chat_{user_id}"})
        if r.deleted_count:
            removed["web_chat_history"] = r.deleted_count
    except PyMongoError as exc:
        logger.warning("[erase] web chat history failed for %s: %s", user_id, exc)
        removed["web_chat_history"] = -1

    logger.info("[erase] %s cleared: %s", user_id, removed)
    # A partial erase is not ok: the caller must not then delete the account row.
    if any(n < 0 for n in removed.values()):
        return {"ok": False, "error": "partial", "removed": removed}
    return {"ok": True, "removed": removed}


def wipe_account_data(user_id: str, keep_nodes: bool = True) -> Dict[str, Any]:
    """Clear everything the account holds but keep the account (and, by default, its robot)."""
    names = [n for n in _BY_USER if not (keep_nodes and n in ("sandy_nodes", "sandy_devices"))]
    return _erase(user_id, names)


def delete_account(user_id: str) -> Dict[str, Any]:
    """Remove every trace of one person; returns per-collection counts."""
    r = _erase(user_id, _BY_USER)
    if not r.get("ok"):
        return r
    removed: Dict[str, int] = r["removed"]

    from app.db import get_db
    db = get_db()

    # Account row last, so a failure above leaves a user who can retry.
    try:
        db["sandy_users"].delete_one({"_id": user_id})
        removed["sandy_users"] = 1
    except PyMongoError as exc:
        logger.warning("[delete] user row failed for %s: %s", user_id, exc)
        return {"ok": False, "error": "partial", "removed": removed}

    # The cache stamp is keyed by id, not a scope field.
    from app.agent.context_builder import clear_directives_cache
    from app.agent.life_snapshot import clear_lists_cache
    from app.utils.tenant_version import forget

    forget(user_id)
    clear_directives_cache()
    clear_lists_cache()
    try:
        from app.api.voice_ws.tools import clear_instruction_cache

        clear_instruction_cache()
    except Exception:  # noqa: BLE001
        logger.debug("[delete] voice instruction cache not cleared", exc_info=True)

    logger.info("[delete] account %s erased: %s", user_id, removed)
    return {"ok": True, "removed": removed}
