"""One version number per tenant, bumped whenever anything they own changes.

The cached voice instruction (`api/voice_ws/tools.py`) is keyed on it. It lives
in the database so both gunicorn workers and the app's own writes invalidate the
same cache; a TTL alone would serve stale data.
"""

from __future__ import annotations

import contextlib
import contextvars
import logging
from typing import Dict, Iterator, Optional

from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

_STAMPS = "sandy_cache_stamps"

# Collections the cached voice instruction is built from: the profile and the log's facts.
VERSIONED = frozenset({"sandy_users", "sandy_entries"})

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


def mark_corrected(tenant: str) -> None:
    """A fact the voice instruction carries was edited or removed: from now on no
    instruction built before this moment may stand in while a new one is built
    (`voice_ws.tools._shared_latest`)."""
    from datetime import datetime, timezone

    key = str(tenant or "")
    coll = _coll()
    if not key or coll is None:
        return
    try:
        coll.update_one({"_id": key},
                        {"$set": {"corrected_at": datetime.now(timezone.utc)}}, upsert=True)
    except PyMongoError as exc:
        logger.warning("[tenant_version] correction stamp failed: %s", exc)


def corrected_at(tenant: str):
    """When a fact of this tenant was last edited or removed (UTC), or None. Unreadable
    reads as now: an older instruction is not served on a guess."""
    from datetime import datetime, timezone

    key = str(tenant or "")
    coll = _coll()
    if not key or coll is None:
        return None
    try:
        doc = coll.find_one({"_id": key}, {"corrected_at": 1}) or {}
    except PyMongoError as exc:
        logger.debug("[tenant_version] correction stamp read failed: %s", exc)
        return datetime.now(timezone.utc)
    stamp = doc.get("corrected_at")
    if stamp is not None and stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)   # pymongo hands back naive UTC
    return stamp


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
