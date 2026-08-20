"""Erasing a person completely.

Apple requires any app that can create an account to be able to delete one, and
they reject for it. But the rule is not why this exists — a Sandy account holds
a voiceprint, a journal, photos, spending, and a transcript of everything its
owner has ever said to her. Somebody who wants that gone is entitled to have it
gone, from the account screen, without emailing anyone.

**The list below is the whole design.** Data is spread across roughly twenty
collections, and a delete that misses one is worse than no delete at all: it
reports success while keeping the diary. So the names are written out here
explicitly rather than discovered at runtime — a collection added later will not
quietly opt itself out of deletion, because adding one means editing this list,
and this file says so.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

try:
    from pymongo.errors import PyMongoError
except ImportError:  # pragma: no cover — the driver is optional for import
    class PyMongoError(Exception):
        pass

logger = logging.getLogger(__name__)

# Keyed by `user_id` — the id every scoped read already filters on.
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
    "sandy_photo_files",
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
]

# Short-term memory keys its documents `"<thread>:<user>"` and also carries a
# `user_id` field (added when memory became cross-channel). Both are cleared:
# the field catches everything written since, the suffix catches what came
# before, and a conversation that survived a deletion would be the single worst
# thing this module could leave behind.
_STM = "sandy_stm"


def _erase(user_id: str, names: List[str]) -> Dict[str, Any]:
    """Clear `names` plus short-term memory for one user. Shared by both paths.

    One implementation on purpose. Two erase routines drift, and the way they
    drift is that one of them stops covering a collection — which is invisible,
    because both still report success.
    """
    from app.db import get_db

    user_id = (user_id or "").strip()
    if not user_id:
        return {"ok": False, "error": "no_user"}
    db = get_db()
    if db is None:
        return {"ok": False, "error": "no_store"}

    removed: Dict[str, int] = {}
    for name in names:
        try:
            r = db[name].delete_many({"user_id": user_id})
            if r.deleted_count:
                removed[name] = r.deleted_count
        # مجموعة وحدة فشلت ما بتوقّف الباقي — والفشل بينسجّل بـ«ناقص واحد»
        # بالنتيجة، فالمالك بيعرف إنّ في إشي ما انمسح بدل ما نقوله «تمام».
        except PyMongoError as exc:
            logger.warning("[erase] %s failed for %s: %s", name, user_id, exc)
            removed[name] = -1

    try:
        r = db[_STM].delete_many({"user_id": user_id})
        n = r.deleted_count
        r2 = db[_STM].delete_many({"key": {"$regex": f":{user_id}$"}})
        n += r2.deleted_count
        if n:
            removed[_STM] = n
    except PyMongoError as exc:
        logger.warning("[erase] stm failed for %s: %s", user_id, exc)
        removed[_STM] = -1

    logger.info("[erase] %s cleared: %s", user_id, removed)
    return {"ok": True, "removed": removed}


def wipe_account_data(user_id: str, keep_nodes: bool = True) -> Dict[str, Any]:
    """Empty an account without destroying it — "start over".

    Deleting and starting over look the same from the data's side and are not
    the same request at all. Someone who wants a clean slate still wants his
    sign-in, his subscription, and above all **his robot**: making him delete
    the account to clear a conversation would cost him the hardware, because a
    node released by a deleted account has to be paired again from scratch.

    So this clears everything the account *holds* and keeps what it *is*.
    """
    names = [n for n in _BY_USER if not (keep_nodes and n in ("sandy_nodes", "sandy_devices"))]
    return _erase(user_id, names)


def delete_account(user_id: str) -> Dict[str, Any]:
    """Remove every trace of one person. Returns what was removed, per collection.

    The counts are returned rather than swallowed because "it worked" is not a
    checkable claim and this is the one operation nobody can undo to verify.
    """
    r = _erase(user_id, _BY_USER)
    if not r.get("ok"):
        return r
    removed: Dict[str, int] = r["removed"]

    from app.db import get_db
    db = get_db()

    # The account row goes last, on purpose. If anything above fails hard, the
    # user still exists and can press the button again — whereas deleting the
    # account first would strand their remaining data with no owner and no way
    # to reach it.
    try:
        db["sandy_users"].delete_one({"_id": user_id})
        removed["sandy_users"] = 1
    except PyMongoError as exc:
        logger.warning("[delete] user row failed for %s: %s", user_id, exc)
        return {"ok": False, "error": "partial", "removed": removed}

    logger.info("[delete] account %s erased: %s", user_id, removed)
    return {"ok": True, "removed": removed}
