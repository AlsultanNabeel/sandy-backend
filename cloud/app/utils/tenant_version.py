"""One version number per tenant, bumped whenever anything they own changes.

Cached persona/context blocks are keyed on it. It lives in the database so
both gunicorn workers and writes that bypass the agent (the app's API routes)
all invalidate the same cache; a TTL alone would serve stale data.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from typing import Dict, Iterator, Optional

from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

_STAMPS = "sandy_cache_stamps"

# Collections the cached persona block is built from.
VERSIONED = frozenset({
    "sandy_memories",
    "sandy_users",
    "sandy_tasks",
    "sandy_reminders",
    "sandy_habits",
    "sandy_habit_log",
    "sandy_books",
    "sandy_reading_sessions",
    "sandy_reading_meta",
    "sandy_journal",
    "sandy_shopping",
    "sandy_goals",
    "sandy_expenses",
    "sandy_focus",
    "sandy_focus_meta",
})

# Memo lives for one turn only (turn_scope); a cross-turn memo would hide
# writes made on the other worker.
_TURN_MEMO: contextvars.ContextVar[Optional[Dict[str, int]]] = contextvars.ContextVar(
    "tenant_version_turn_memo", default=None)


def detach_turn_memo() -> None:
    """انسَ نسخ هالدور — لمهمّة خلفية ورثت سياقه (وإلا بتقرا رقم نسخة قديم)."""
    _TURN_MEMO.set(None)


@contextlib.contextmanager
def turn_scope() -> Iterator[None]:
    """Remember each tenant's version for one turn (shared by jobs with a copied context)."""
    token = _TURN_MEMO.set({})
    try:
        yield
    finally:
        _TURN_MEMO.reset(token)


def _coll():
    from app.db import get_db

    db = get_db()
    return None if db is None else db[_STAMPS]


def version_for(tenant: str) -> int:
    """Current version, 0 if never bumped, or -1 (never matches a cache) when unreadable."""
    key = str(tenant or "")
    if not key:
        return -1

    memo = _TURN_MEMO.get()
    if memo is not None and key in memo:
        return memo[key]

    coll = _coll()
    if coll is None:
        return -1
    try:
        doc = coll.find_one({"_id": key}, {"v": 1})
        version = int((doc or {}).get("v") or 0)
    except PyMongoError as exc:
        logger.debug("[tenant_version] read failed: %s", exc)
        return -1
    if memo is not None:
        memo[key] = version
    return version


def bump_for(tenant: str, *, collection: Optional[str] = None) -> None:
    """Mark a tenant's cache stale for every worker. Synchronous on purpose.

    Writes to collections outside VERSIONED are ignored; ``collection=None`` forces a bump.
    """
    key = str(tenant or "")
    if not key:
        return
    if collection is not None and collection not in VERSIONED:
        return

    coll = _coll()
    if coll is None:
        return
    try:
        coll.update_one({"_id": key}, {"$inc": {"v": 1}}, upsert=True)
        # After the write: a racing read could otherwise re-memo the old number.
        memo = _TURN_MEMO.get()
        if memo is not None:
            memo.pop(key, None)
        logger.info("[tenant_version] %s bumped by %s", key, collection or "?")
    except PyMongoError as exc:
        logger.debug("[tenant_version] bump failed: %s", exc)
        return
    from app.utils.prompt_prewarm import schedule

    schedule(key)


def forget(tenant: str) -> None:
    """Drop a tenant's stamp (account deletion)."""
    key = str(tenant or "")
    if not key:
        return
    coll = _coll()
    if coll is None:
        return
    try:
        coll.delete_one({"_id": key})
    except PyMongoError as exc:
        logger.debug("[tenant_version] forget failed: %s", exc)
