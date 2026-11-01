"""The log of what happened to his data (owner, 30 Oct 2026): every change to a list's item, a
log entry or a schedule, written in the same transaction as the change itself (`_base.write`),
so both are kept or neither is.

An event is `{seq, at, coll, op, row, kind, list, from_list, label, before, after, source,
expire_at}` (`label` the row's words now, or as it was when removed, so a tick is told by name;
`from_list` the list an item moved away from, so a task on that list sees it go):
  op       added, removed, done, reopened, edited, hidden (a done item cleared from view)
  before   what the row was (whole for a removal, the changed fields for an edit)
  after    what it is now (whole for an addition, the changed fields for an edit)
  source   who changed it: chat, voice (the app's call), robot, app, system (`using_source`)
  seq      his own count, one up per event: what a task reads from (`since`)

Sealed words stay sealed: the row's values are copied as they are kept. An event lives
`KEEP_DAYS` (TTL on `expire_at`) and goes with the account and with a reset.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Any, Dict, Iterator, List, Mapping, Optional

from pymongo import ReturnDocument
from pymongo.errors import PyMongoError

from app.blocks import _base

logger = logging.getLogger(__name__)

EVENTS = "sandy_events"
COUNTERS = "sandy_event_seq"
KEEP_DAYS = 90
SOURCES = ("chat", "voice", "robot", "app", "system")
# What a row carries that is no part of what he sees.
_INNER = frozenset({"_id", "user_id", "embedding", "armed", "armed_once", "claimed_until",
                    "fire_tries", "fired_at", "last_error", "series_start", "migrated_from"})

_source: ContextVar[str] = ContextVar("blocks_event_source", default="system")


def init_events(mongo_db) -> None:
    if mongo_db is None:
        return
    for keys, extra in (([("user_id", 1), ("seq", 1)], {}),
                        ([("expire_at", 1)], {"expireAfterSeconds": 0})):
        try:
            mongo_db[EVENTS].create_index(keys, background=True, **extra)
        except PyMongoError as exc:  # one index never stops the boot
            logger.warning("[events] index %s skipped: %s", keys, exc)


@contextmanager
def using_source(source: str) -> Iterator[None]:
    """The changes made inside are his through ``source`` (chat, voice, robot, app)."""
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
    token = _source.set(source)
    try:
        yield
    finally:
        _source.reset(token)


def current_source() -> str:
    return _source.get()


def _seen(row: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    return {k: v for k, v in (row or {}).items() if k not in _INNER}


def _what(op: str, before: Dict[str, Any], after: Dict[str, Any]) -> str:
    if op == "created":
        return "added"
    if op == "deleted":
        return "removed"
    if after.get("hidden_at") and not before.get("hidden_at"):
        return "hidden"
    if "done" in after and bool(before.get("done")) != bool(after.get("done")):
        return "done" if after.get("done") else "reopened"
    return "edited"


def _next_seq(session) -> int:
    from app.utils.user_profiles import current_user_id

    counters = _base.coll(COUNTERS)
    row = counters.find_one_and_update({"_id": str(current_user_id() or "")}, {"$inc": {"n": 1}},
                                       upsert=True, return_document=ReturnDocument.AFTER,
                                       session=session)
    return int(row["n"])


def add(name: str, op: str, row_id: str, before: Optional[Mapping[str, Any]],
        after: Optional[Mapping[str, Any]], *, session=None) -> Optional[int]:
    """Write the event of one change, inside its transaction (``session``); its seq. Raises
    as the database does: the change goes with it."""
    coll = _base.coll(EVENTS)
    if coll is None:
        return None
    old, new = _seen(before), _seen(after)
    if op == "updated":
        keys = sorted(k for k in set(old) | set(new) if old.get(k) != new.get(k))
        if not keys:
            return None
        old, new = {k: old.get(k) for k in keys}, {k: new.get(k) for k in keys}
        what = _what(op, _seen(before), _seen(after))
    else:
        what = _what(op, old, new)
    whole = _seen(after) or _seen(before)
    moved_from = (before or {}).get("list") if after and before and \
        before.get("list") != after.get("list") else None
    at = _base.now()
    seq = _next_seq(session)
    coll.insert_one({"_id": _base.new_id(), "seq": seq, "at": at, "coll": name, "op": what,
                     "row": str(row_id), "kind": whole.get("kind"), "list": whole.get("list"),
                     **({"from_list": moved_from} if moved_from else {}),
                     "label": whole.get("text"),
                     "before": old or None, "after": new or None, "source": current_source(),
                     "expire_at": at + timedelta(days=KEEP_DAYS)}, session=session)
    return seq


def since(seq: int, *, limit: int = 500) -> List[Dict[str, Any]]:
    """His events after ``seq``, oldest first."""
    coll = _base.coll(EVENTS)
    if coll is None:
        return []
    return list(coll.find({"seq": {"$gt": int(seq or 0)}}).sort("seq", 1).limit(limit))


def seq_at(at) -> int:
    """Where his log was at ``at`` (0 before his first event)."""
    coll = _base.coll(EVENTS)
    row = coll.find_one({"at": {"$lte": at}}, sort=[("seq", -1)]) if coll is not None else None
    return int((row or {}).get("seq") or 0)


def last_seq() -> int:
    """Where his log is now (0 before his first event)."""
    from app.utils.user_profiles import current_user_id

    counters = _base.coll(COUNTERS)
    row = counters.find_one({"_id": str(current_user_id() or "")}) if counters is not None else None
    return int((row or {}).get("n") or 0)
