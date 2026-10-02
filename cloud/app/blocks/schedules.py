"""SCHEDULES block (sandy_schedules): anything that fires at a time.

{user_id, kind, text, fire_at, recurrence (RRULE or ""), payload, status, migrated_from}
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from app.blocks import _base
from app.blocks.kinds import SCHEDULE, validate

logger = logging.getLogger(__name__)

STATUSES = ("pending", "sent", "failed", "cancelled")


def init_schedules_store(mongo_db) -> None:
    if mongo_db is None:
        return
    for keys in ([("user_id", 1), ("status", 1), ("fire_at", 1)],
                 [("user_id", 1), ("kind", 1), ("fire_at", 1)],
                 [("user_id", 1), ("migrated_from.collection", 1), ("migrated_from.id", 1)]):
        try:
            mongo_db[_base.SCHEDULES].create_index(keys, background=True)
        except Exception as exc:  # noqa: BLE001 — one failed index must not skip the rest
            logger.warning("[blocks] schedules index %s skipped: %s", keys, exc)


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
    coll.insert_one(doc)
    _base.noted("created", _base.SCHEDULES, doc["_id"], text=doc["text"])
    return doc["_id"]


def get(schedule_id: str, mongo_db=None) -> Optional[Dict[str, Any]]:
    coll = _base.coll(_base.SCHEDULES, mongo_db)
    if coll is None or not schedule_id:
        return None
    return _base.out(coll.find_one({"_id": schedule_id}))


def update(schedule_id: str, *, text: Optional[str] = None,
           fire_at: Optional[datetime] = None, recurrence: Optional[str] = None,
           payload: Optional[Mapping[str, Any]] = None, status: Optional[str] = None,
           mongo_db=None) -> bool:
    """Change fields; True when the schedule exists."""
    coll = _base.coll(_base.SCHEDULES, mongo_db)
    if coll is None or not schedule_id:
        return False
    current = coll.find_one({"_id": schedule_id}, {"kind": 1})
    if current is None:
        return False
    changes: Dict[str, Any] = {}
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
    if changes:
        _base.noted("updated", _base.SCHEDULES, schedule_id, coll)
        coll.update_one({"_id": schedule_id}, {"$set": changes})
    return True


def delete(schedule_id: str, mongo_db=None) -> bool:
    coll = _base.coll(_base.SCHEDULES, mongo_db)
    if coll is None or not schedule_id:
        return False
    _base.noted("deleted", _base.SCHEDULES, schedule_id, coll)
    return coll.delete_one({"_id": schedule_id}).deleted_count > 0


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
