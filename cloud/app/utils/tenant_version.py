"""One number per tenant, bumped whenever anything they own changes.

`get_persona_directives` is the most expensive thing in a chat turn — measured
at 32 of the 41 database round trips a user waits for, and roughly four of the
nine seconds a reply took in production. It rebuilds "what Sandy knows about
you" from scratch on every message: tasks, habits, books, journal, shopping,
preferences, relationships, lessons, summaries, onboarding.

Caching it is obvious. **Getting the invalidation wrong is what makes it a
lie**, and a first attempt at this was cut from the audit for exactly that:

* a plain TTL means "add a task" then "what are my tasks" answers from before
  the task existed;
* `Procfile` runs two workers, so a process-local invalidation reaches one of
  them and the next message lands on whichever is free;
* and most writes never touch the agent at all — the phone app writes tasks and
  habits through `api/*_api.py`, `users_store` writes the onboarding profile on
  a raw handle, `api/memory_api.py` writes preferences the same way.

A version stamp answers all three, because the question moves into the database
where every process and every path sees the same answer. One small read per turn
tells a worker whether what it holds is still current; that is one round trip
against thirty-two.

**The bump has to sit where the write is.** `ScopedCollection` covers most of
them, and `bump_for` is called directly by the handful that reach past it — the
places the first attempt assumed did not exist. Only collections a cached block
is actually built from count, so short-term memory and the usage counters, which
change every single turn, do not defeat the cache they have nothing to do with.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

_STAMPS = "sandy_cache_stamps"

# The collections a cached persona block is built from. `build_life_snapshot`
# and `search_life` read the life stores; `get_persona_directives` reads
# `sandy_memories`; the onboarding line comes from `sandy_users`.
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

# A read-through memo, so a burst of turns for one tenant does not each pay for
# the version lookup. **This is the only staleness left in the design**, and it
# is bounded by this number: a change made on the other worker is invisible for
# at most this long. Kept short deliberately — the round trip it saves is one,
# and the thing it can cost is Sandy contradicting the app.
_MEMO_TTL_S = 3.0
_memo: Dict[str, Tuple[float, int]] = {}
_lock = threading.Lock()


def _coll():
    from app.db import get_db

    db = get_db()
    return None if db is None else db[_STAMPS]


def version_for(tenant: str) -> int:
    """Current version for a tenant, or 0 when it cannot be read.

    0 on failure is deliberate: a version that cannot be read never matches a
    stored one, so the cache misses and the caller rebuilds. Degrading costs
    round trips, never accuracy — which is the right direction for a cache.
    """
    key = str(tenant or "")
    if not key:
        return 0

    now = time.monotonic()
    with _lock:
        hit = _memo.get(key)
        if hit and hit[0] > now:
            return hit[1]

    coll = _coll()
    if coll is None:
        return 0
    try:
        doc = coll.find_one({"_id": key}, {"v": 1})
        version = int((doc or {}).get("v") or 0)
    except PyMongoError as exc:
        logger.debug("[tenant_version] read failed: %s", exc)
        return 0

    with _lock:
        _memo[key] = (now + _MEMO_TTL_S, version)
        if len(_memo) > 512:      # bounded: one entry per recently-seen tenant
            _memo.clear()
    return version


def bump_for(tenant: str, *, collection: Optional[str] = None) -> None:
    """Mark a tenant's cached context stale, for every worker.

    `collection` is the name that was written; anything outside `VERSIONED` is
    ignored, so the per-turn stores do not invalidate a cache they have nothing
    to do with. Pass `None` to force a bump when the caller knows something
    changed but not which collection.

    The memo is dropped synchronously and the database write is fired onto the
    background pool: the write is what other workers see, and the process that
    made the change must not read its own stale memo in the meantime.
    """
    key = str(tenant or "")
    if not key:
        return
    if collection is not None and collection not in VERSIONED:
        return

    with _lock:
        _memo.pop(key, None)

    def _apply() -> None:
        coll = _coll()
        if coll is None:
            return
        try:
            coll.update_one({"_id": key}, {"$inc": {"v": 1}}, upsert=True)
        except PyMongoError as exc:
            logger.debug("[tenant_version] bump failed: %s", exc)

    from app.utils.thread_pool import submit_background

    submit_background(_apply, _label="tenant-version")


def reset_for_tests() -> None:
    """Drop the read-through memo. Test-only."""
    with _lock:
        _memo.clear()


def snapshot_for_tests() -> Dict[str, Any]:
    with _lock:
        return dict(_memo)
