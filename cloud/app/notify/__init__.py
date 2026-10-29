"""What a task found, delivered: the one way out of a task (`brain/task_runner.py`).

`deliver` keeps the result under its user (`sandy_task_results`: what the app shows, and what
«صباح الخير» tells him when he speaks; `unseen` / `mark_seen`), then hands it to each channel
in `CHANNELS`, a callable taking the result row: email now (`mail.py`), Apple's pushes beside
it later. `flush` gives each channel the chance to send what it held for the current user
(`FLUSHES`), every minute from the schedule runner (`users_with_held`). A channel that
fails is logged and never loses the result. None of it speaks: Sandy never talks on her own.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from pymongo.errors import PyMongoError

from app.blocks import _base
from app.notify import mail

logger = logging.getLogger(__name__)

RESULTS = "sandy_task_results"

# Each takes the result row as `deliver` kept it.
CHANNELS: List[Callable[[Dict[str, Any]], None]] = [mail.send]
# Each sends what it held for the current user that may go now.
FLUSHES: List[Callable[[], None]] = [mail.flush]


def deliver(task_id: str, title: str, body: str, language: str) -> str:
    """Keep the result and send it through every channel; its id ("" with no tenant)."""
    coll = _base.coll(RESULTS)
    if coll is None:
        return ""
    row = {"_id": _base.new_id(), "task_id": str(task_id), "title": str(title or ""),
           "body": str(body or ""), "lang": language, "at": datetime.now(timezone.utc),
           "seen": False}
    coll.insert_one(row)
    from app.services import schedule_sync
    schedule_sync.changed("task")       # the Tasks screen shows it at once
    out = {**row, "id": row["_id"]}
    for channel in CHANNELS:
        try:
            channel(out)
        except (OSError, RuntimeError, ValueError):  # SMTP's errors are OSErrors; kept anyway
            logger.exception("[notify] a channel failed for task %s", task_id)
    return row["_id"]


def flush() -> None:
    """Each channel sends what it held for the current user, when it may."""
    for channel in FLUSHES:
        try:
            channel()
        except (OSError, RuntimeError, ValueError):
            logger.exception("[notify] a channel's held results failed")


def users_with_held(mongo_db) -> List[str]:
    """Accounts with a result a channel holds (raw cross-tenant read; only ids leave)."""
    if mongo_db is None:
        return []
    try:
        return [str(u) for u in mongo_db[RESULTS].distinct("user_id", {"email": mail.HELD}) if u]
    except PyMongoError as exc:  # one failed scan waits for the next minute
        logger.warning("[notify] held scan failed: %s", exc)
        return []


def unseen(limit: int = 20) -> List[Dict[str, Any]]:
    """The results he has not seen yet, newest first."""
    coll = _base.coll(RESULTS)
    if coll is None:
        return []
    rows = coll.find({"seen": False}).sort("at", -1).limit(limit)
    return [{**{k: v for k, v in r.items() if k not in ("_id", "user_id")}, "id": r["_id"]}
            for r in rows]


def mark_seen(ids: List[str]) -> None:
    coll = _base.coll(RESULTS)
    if coll is not None and ids:
        coll.update_many({"_id": {"$in": list(ids)}}, {"$set": {"seen": True}})


def of_task(task_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """One task's results, newest first."""
    coll = _base.coll(RESULTS)
    if coll is None:
        return []
    rows = coll.find({"task_id": str(task_id)}).sort("at", -1).limit(limit)
    return [_base.out(r) for r in rows]


def unseen_by_task() -> Dict[str, int]:
    """How many results of each task he has not seen."""
    coll = _base.coll(RESULTS)
    counts: Dict[str, int] = {}
    for r in coll.find({"seen": False}, {"task_id": 1}) if coll is not None else []:
        counts[r["task_id"]] = counts.get(r["task_id"], 0) + 1
    return counts


def seen_all(task_id: str) -> None:
    coll = _base.coll(RESULTS)
    if coll is not None:
        coll.update_many({"task_id": str(task_id), "seen": False}, {"$set": {"seen": True}})


def forget_task(task_id: str) -> None:
    """A removed task's results go with it."""
    coll = _base.coll(RESULTS)
    if coll is not None:
        coll.delete_many({"task_id": str(task_id)})
