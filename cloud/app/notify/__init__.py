"""What a task found, delivered: the one way out of a task (`brain/task_runner.py`).

`deliver` keeps the result under its user (`sandy_task_results`: what the app shows, and what
«صباح الخير» tells him when he speaks; `unseen` / `mark_seen`), then hands it to each channel
in `CHANNELS`, a callable taking the result row: email now (`mail.py`), Apple's pushes beside
it later. `flush` is a task's run giving a channel what it held (`FLUSHES`). A channel that
fails is logged and never loses the result. None of it speaks: Sandy never talks on her own.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from app.blocks import _base
from app.notify import mail

logger = logging.getLogger(__name__)

RESULTS = "sandy_task_results"

# Each takes the result row as `deliver` kept it.
CHANNELS: List[Callable[[Dict[str, Any]], None]] = [mail.send]
# Each takes a task's id when it runs, and sends what it held for it.
FLUSHES: List[Callable[[str], None]] = [mail.flush]


def deliver(task_id: str, title: str, body: str, language: str) -> str:
    """Keep the result and send it through every channel; its id ("" with no tenant)."""
    coll = _base.coll(RESULTS)
    if coll is None:
        return ""
    row = {"_id": _base.new_id(), "task_id": str(task_id), "title": str(title or ""),
           "body": str(body or ""), "lang": language, "at": datetime.now(timezone.utc),
           "seen": False}
    coll.insert_one(row)
    out = {**row, "id": row["_id"]}
    for channel in CHANNELS:
        try:
            channel(out)
        except (OSError, RuntimeError, ValueError):  # SMTP's errors are OSErrors; kept anyway
            logger.exception("[notify] a channel failed for task %s", task_id)
    return row["_id"]


def flush(task_id: str) -> None:
    """A task runs: each channel sends what it held for it, when it may."""
    for channel in FLUSHES:
        try:
            channel(str(task_id))
        except (OSError, RuntimeError, ValueError):
            logger.exception("[notify] a channel's held results failed for task %s", task_id)


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
