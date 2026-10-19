"""What was changed in the blocks, kept seven days so it can be put back (`sandy_changes`).

Every delete keeps the row as it was, wherever it came from (Sandy, the app's screens):
the row leaves its list at once and waits here, marked deleted, until the TTL index takes
it after `KEEP_DAYS`. While Sandy's turn runs (chat, or a call's tool), its adds and edits
are kept too, with the turn they belong to (`recording`). That is what «تراجعي»، «لا
رجّعيه»، «رجّعي الحليب» undo, any number of messages later and more than one at a time
(`brain.tools_blocks.undo`), and the app's «تراجع» button after a reply (`POST /api/undo`).

Each row: {_id, user_id, at, turn, op: created|updated|deleted, coll, row, before, label,
undone_at}. ``before`` is the row as it was (no vector, no tenant); ``label`` names it.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import timedelta
from typing import Any, Dict, Iterator, List, Optional

from pymongo.errors import PyMongoError

from app.blocks import _base

logger = logging.getLogger(__name__)

CHANGES = "sandy_changes"
KEEP_DAYS = 7
RECENT = 200

_turn: ContextVar[Optional[str]] = ContextVar("blocks_change_turn", default=None)


def init_changes_store(mongo_db) -> None:
    raw = mongo_db[CHANGES]
    for keys, opts in (([("user_id", 1), ("at", -1)], {"name": "user_at"}),
                       ([("user_id", 1), ("turn", 1)], {"name": "user_turn"}),
                       ([("at", 1)], {"name": "at_ttl",
                                      "expireAfterSeconds": KEEP_DAYS * 86400})):
        try:
            raw.create_index(keys, **opts)
        except PyMongoError as exc:  # one index failing never skips the rest
            logger.warning("[changes] index %s failed: %s", opts["name"], exc)


@contextmanager
def recording(turn: str) -> Iterator[str]:
    """Inside it, every block write is kept under ``turn`` (one reply, or one tool of a call)."""
    token = _turn.set(turn)
    try:
        yield turn
    finally:
        _turn.reset(token)


def current_turn() -> Optional[str]:
    return _turn.get()


def keep(op: str, name: str, row_id: str, before: Optional[Dict[str, Any]], label: str) -> None:
    """Keep one write: a delete always, an add or an edit while a turn is recorded."""
    turn = _turn.get()
    if turn is None and op != "deleted":
        return
    coll = _base.coll(CHANGES)
    if coll is None:
        return
    try:
        coll.insert_one({"_id": _base.new_id(), "at": _base.now(), "turn": turn or _base.new_id(),
                         "op": op, "coll": name, "row": row_id, "before": before,
                         "label": label, "undone_at": None})
    except PyMongoError as exc:  # the write itself stands
        logger.warning("[changes] not kept: %s", exc)


def recent(limit: int = RECENT) -> List[Dict[str, Any]]:
    """Changes not yet undone, newest first."""
    coll = _base.coll(CHANGES)
    if coll is None:
        return []
    since = _base.now() - timedelta(days=KEEP_DAYS)
    return list(coll.find({"undone_at": None, "at": {"$gte": since}})
                .sort([("at", -1), ("_id", -1)]).limit(limit))


def of_turn(turn: str) -> List[Dict[str, Any]]:
    """A turn's changes not yet undone, newest first."""
    return [c for c in recent() if c.get("turn") == turn]


def undo(picked: List[Dict[str, Any]]) -> int:
    """Puts ``picked`` back (newest first, as `recent` gives them): a deleted row comes back
    as it was, same id, text, dates, reminder and place in its list; an edited one gets its
    old values; an added one goes. The count of rows put right."""
    if not picked:
        return 0
    effects = [{"op": c["op"], "coll": c["coll"], "id": c["row"], "before": c.get("before")}
               for c in reversed(picked)]
    done = _base.undo(effects)
    coll = _base.coll(CHANGES)
    if coll is not None:
        coll.update_many({"_id": {"$in": [c["_id"] for c in picked]}},
                         {"$set": {"undone_at": _base.now()}})
    return done
