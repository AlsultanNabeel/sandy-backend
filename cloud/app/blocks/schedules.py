"""SCHEDULES block (sandy_schedules): anything that fires at a time.

{user_id, kind, text, fire_at, recurrence (RRULE or ""), series_start, payload, status,
migrated_from}

A repeating row keeps where its series began (`series_start`: the wall time on the user's
clock, no zone), so a rule with a count or an end is counted from there and not from each
ring's own time, and «every day at 8» is eight on whatever clock the user is on now.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional

from app.blocks import _base
from app.blocks.kinds import SCHEDULE, validate
from app.utils.time import USER_TZ

logger = logging.getLogger(__name__)

STATUSES = ("pending", "sent", "failed", "cancelled")


def init_schedules_store(mongo_db) -> None:
    if mongo_db is None:
        return
    # The runner's due scan crosses every tenant, so it has its own index, led by status.
    for keys in ([("status", 1), ("fire_at", 1)],
                 [("user_id", 1), ("status", 1), ("fire_at", 1)],
                 [("user_id", 1), ("kind", 1), ("fire_at", 1)],
                 [("user_id", 1), ("migrated_from.collection", 1), ("migrated_from.id", 1)]):
        try:
            mongo_db[_base.SCHEDULES].create_index(keys, background=True)
        except Exception as exc:  # noqa: BLE001 — one failed index must not skip the rest
            logger.warning("[blocks] schedules index %s skipped: %s", keys, exc)


def series_start(fire_at: datetime) -> str:
    """The wall time on the user's clock a series starts at, kept without a zone."""
    at = fire_at if fire_at.tzinfo else fire_at.replace(tzinfo=timezone.utc)
    return at.astimezone(USER_TZ).replace(tzinfo=None).isoformat(timespec="seconds")


def series_anchor(doc: Mapping[str, Any]) -> datetime:
    """Where a repeating row's series begins, on the user's current clock; a row saved
    before the start was kept is anchored at its own time."""
    start = doc.get("series_start")
    if start:
        return datetime.fromisoformat(start).replace(tzinfo=USER_TZ)
    at = doc["fire_at"]
    return (at if at.tzinfo else at.replace(tzinfo=timezone.utc)).astimezone(USER_TZ)


def _check_status(status: str) -> str:
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")
    return status


def add(kind: str, text: str, fire_at: datetime, payload: Optional[Mapping[str, Any]] = None, *,
        recurrence: str = "", status: str = "pending",
        created_at: Optional[datetime] = None,
        migrated_from: Optional[Mapping[str, Any]] = None,
        doc_id: Optional[str] = None, mongo_db=None) -> str:
    """New schedule id, or "" with no tenant. Bad kind/payload raises KindError."""
    clean = validate(SCHEDULE, kind, payload)
    _check_status(status)
    if not isinstance(fire_at, datetime):
        raise ValueError("fire_at must be a datetime")
    coll = _base.coll(_base.SCHEDULES, mongo_db)
    if coll is None:
        return ""
    doc = {
        "_id": doc_id or _base.new_id(),
        "kind": kind,
        "text": str(text or "").strip(),
        "fire_at": fire_at,
        "recurrence": str(recurrence or "").strip(),
        "payload": clean,
        "status": status,
        "created_at": created_at or _base.now(),
        "migrated_from": _base.migrated_ref(migrated_from),
    }
    if doc["recurrence"]:
        doc["series_start"] = series_start(fire_at)
    coll.insert_one(doc)
    _base.noted("created", _base.SCHEDULES, doc["_id"], text=doc["text"])
    _phone_told(kind)
    return doc["_id"]


def get(schedule_id: str, mongo_db=None) -> Optional[Dict[str, Any]]:
    coll = _base.coll(_base.SCHEDULES, mongo_db)
    if coll is None or not schedule_id:
        return None
    return _base.out(coll.find_one({"_id": schedule_id}))


def update(schedule_id: str, *, text: Optional[str] = None,
           fire_at: Optional[datetime] = None, recurrence: Optional[str] = None,
           payload: Optional[Mapping[str, Any]] = None, status: Optional[str] = None,
           keep_series: bool = False, mongo_db=None) -> bool:
    """Change fields; True when the schedule exists. A new time or repeat starts the
    series again from the row's time, unless ``keep_series`` (a skipped occurrence)."""
    coll = _base.coll(_base.SCHEDULES, mongo_db)
    if coll is None or not schedule_id:
        return False
    current = coll.find_one({"_id": schedule_id}, {"kind": 1, "fire_at": 1, "recurrence": 1})
    if current is None:
        return False
    changes: Dict[str, Any] = {}
    unset: Dict[str, str] = {}
    if text is not None:
        changes["text"] = str(text).strip()
    if fire_at is not None:
        changes["fire_at"] = fire_at
    if recurrence is not None:
        changes["recurrence"] = str(recurrence).strip()
    if payload is not None:
        changes["payload"] = validate(SCHEDULE, current["kind"], payload)
    if status is not None:
        changes["status"] = _check_status(status)
    if (fire_at is not None or recurrence is not None) and not keep_series:
        if changes.get("recurrence", current.get("recurrence")):
            changes["series_start"] = series_start(changes.get("fire_at", current["fire_at"]))
        else:
            unset["series_start"] = ""
    if changes or unset:
        _base.noted("updated", _base.SCHEDULES, schedule_id, coll)
        coll.update_one({"_id": schedule_id},
                        {**({"$set": changes} if changes else {}),
                         **({"$unset": unset} if unset else {})})
        _phone_told(current["kind"])
    return True


def snooze(row: Mapping[str, Any], minutes: int, now: datetime) -> Optional[str]:
    """Ring a reminder that rang once more, ``minutes`` from now; the id that will ring.
    A one-off goes back to pending at the new time; a repeat gets a one-time copy (its
    payload kept, so an alarm stays an alarm) and its series is left as it is. Shared by
    `POST /api/schedules/<id>/snooze` (the notification's «later») and `schedule_update`."""
    at = now + timedelta(minutes=minutes)
    if row.get("recurrence"):
        return add(row.get("kind") or "reminder", row.get("text", ""), at,
                   row.get("payload") or None) or None
    return row["id"] if update(row["id"], fire_at=at, status="pending") else None


def delete(schedule_id: str, mongo_db=None) -> bool:
    coll = _base.coll(_base.SCHEDULES, mongo_db)
    if coll is None or not schedule_id:
        return False
    row = coll.find_one({"_id": schedule_id}, {"kind": 1})
    if row is None:
        return False
    _base.noted("deleted", _base.SCHEDULES, schedule_id, coll)
    gone = coll.delete_one({"_id": schedule_id}).deleted_count > 0
    if gone:
        _phone_told(row["kind"])
    return gone


def _phone_told(kind: str) -> None:
    """Every write here reaches the user's phones (`services/schedule_sync`)."""
    from app.services import schedule_sync

    schedule_sync.changed(kind)


def list_schedules(kind: Optional[str] = None, *, status: Optional[str] = None,
                   since: Optional[datetime] = None, until: Optional[datetime] = None,
                   text: str = "", fired_since: Optional[datetime] = None,
                   limit: int = 200, mongo_db=None) -> List[Dict[str, Any]]:
    """Soonest first; ``since``/``until`` bound ``fire_at``, ``fired_since`` the last ring;
    every filter optional."""
    coll = _base.coll(_base.SCHEDULES, mongo_db)
    if coll is None:
        return []
    query: Dict[str, Any] = {}
    if kind:
        query["kind"] = kind
    if status:
        query["status"] = status
    rng = _base.range_filter(since, until)
    if rng:
        query["fire_at"] = rng
    if text:
        query.update(_base.text_filter(text))
    if fired_since is not None:
        query["fired_at"] = {"$gte": fired_since}
    cursor = coll.find(query).sort("fire_at", 1).limit(_base.clamp(limit))
    return [_base.out(d) for d in cursor]
