"""«إيقاف» from the app: a reply stopped midway.

The running turn checks between its steps and runs no further tool once stopped, and
Sandy's memory of the thread keeps only what was shown, marked as cut, so she knows
the user did not get the rest. One doc per thread in `turn_stops`, taken by the turn.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from app.db import get_db

_COLL = "turn_stops"
# A stop older than this belongs to a turn long over.
_FRESH = timedelta(minutes=10)
CUT_NOTE = "[وقّف الرد هون قبل ما أكمّل، فما وصله الباقي]"


def _key(user_id: str, thread_id: str) -> str:
    return f"{user_id}:{thread_id}"


def request(user_id: str, thread_id: str, partial: str) -> None:
    db = get_db()
    if db is None:
        return
    db[_COLL].replace_one({"_id": _key(user_id, thread_id)},
                          {"partial": partial, "at": datetime.now(timezone.utc)}, upsert=True)


def _fresh(doc, since: Optional[datetime]) -> bool:
    """Recent, and made while this turn ran (`since` = when it began): a stop that
    arrived as the previous turn ended must not cut the next one."""
    at = (doc or {}).get("at")
    if not isinstance(at, datetime):
        return False
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if since is not None and at < since:
        return False
    return datetime.now(timezone.utc) - at < _FRESH


def requested(user_id: str, thread_id: str, since: Optional[datetime] = None) -> bool:
    db = get_db()
    return db is not None and _fresh(db[_COLL].find_one({"_id": _key(user_id, thread_id)}), since)


def take(user_id: str, thread_id: str, since: Optional[datetime] = None) -> Optional[str]:
    """What was shown before the stop, once (the request is used up), or None."""
    db = get_db()
    if db is None:
        return None
    doc = db[_COLL].find_one_and_delete({"_id": _key(user_id, thread_id)})
    return str(doc.get("partial") or "") if _fresh(doc, since) else None


def cut(partial: str) -> str:
    """The reply as memory keeps it: what was shown, then the note."""
    return (partial.strip() + "\n" + CUT_NOTE).strip()
