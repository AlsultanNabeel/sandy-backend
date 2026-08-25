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
from typing import Optional

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

# **No read-through memo.** There was one, holding the version for a few seconds
# so a burst of turns would not each pay the lookup. It saves exactly one small
# round trip and costs the only thing this design has: a write on the other
# worker stays invisible for the length of the memo, which is "add a task, ask
# about it, hear that you have none" — the failure the version stamp exists to
# make impossible. One read per turn, always current.


def _coll():
    from app.db import get_db

    db = get_db()
    return None if db is None else db[_STAMPS]


def version_for(tenant: str) -> int:
    """Current version for a tenant, or ``-1`` when it cannot be read.

    ``-1`` is never stored, so a version that cannot be read never matches a
    cached one and the caller rebuilds. Degrading costs round trips, never
    accuracy — the right direction for a cache.

    A tenant with no stamp document is ``0``, which **is** cacheable: an account
    that has not written anything yet is the commonest case on a fresh install,
    and refusing to cache it would exempt exactly the accounts with the least
    data from the saving.
    """
    key = str(tenant or "")
    if not key:
        return -1

    coll = _coll()
    if coll is None:
        return -1
    try:
        doc = coll.find_one({"_id": key}, {"v": 1})
        version = int((doc or {}).get("v") or 0)
    except PyMongoError as exc:
        logger.debug("[tenant_version] read failed: %s", exc)
        return -1
    return version


def bump_for(tenant: str, *, collection: Optional[str] = None) -> None:
    """Mark a tenant's cached context stale, for every worker.

    `collection` is the name that was written; anything outside `VERSIONED` is
    ignored, so the per-turn stores do not invalidate a cache they have nothing
    to do with. Pass `None` to force a bump when the caller knows something
    changed but not which collection. A writer inside a versioned collection
    that still runs every turn opts out at the call site instead — see
    `scoped(..., bump=False)`.

    **Both halves are synchronous, and that is the whole point.** The bump was
    on the background pool at first, which leaves a window: add a task on one
    worker, ask about it on the other a moment later, and the second worker
    reads a version the first has not written yet and answers from the cache —
    "you have no tasks", about a task that exists. A cache that can do that is
    worse than no cache. The cost is one small upsert on a write path that has
    already paid for a round trip; reads outnumber writes by a wide margin here.
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
    except PyMongoError as exc:
        logger.debug("[tenant_version] bump failed: %s", exc)


def forget(tenant: str) -> None:
    """Drop a tenant's stamp entirely — for account deletion.

    Left behind, it is a row keyed by the id of an account that no longer
    exists, and it would hand a stale version to whoever reuses that id.
    """
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
