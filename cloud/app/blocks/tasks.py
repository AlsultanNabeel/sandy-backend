"""Tasks: work Sandy does on her own at its time (`brain/task_runner.py`), set up by talk.

A task is a `sandy_schedules` row of kind «task», so the minute runner claims, fires and
moves it on like any other row. It repeats every N minutes (an RRULE), may be paused
(`status: paused`, never due), and carries what to do in its payload: the user's own words
(`instructions`), a check the code runs first (`probe`: one read tool and its arguments),
what is worth telling (`notify_when`), the tools the model may use, the language and whether
it is urgent. Nothing in it names a field of work: a student's deadlines, a freelancer's new
projects, a shop's stock and a home's budget are the same row with other words.

What it saw last (a fingerprint of the probe, the last result, the failures in a row) is in
`sandy_task_state`, one row per task under its user, removed with the task.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from app.blocks import _base, schedules

KIND = "task"
STATE = "sandy_task_state"


def _rule(every_minutes: int) -> str:
    minutes = int(every_minutes)
    if minutes <= 0:
        raise ValueError("every_minutes must be above zero")
    return f"FREQ=MINUTELY;INTERVAL={minutes}"


def add(title: str, spec: Mapping[str, Any], *, every_minutes: int, first_at: datetime) -> str:
    """The new task's id ("" with no tenant). Bad payload raises KindError."""
    return schedules.add(KIND, title, first_at, dict(spec), recurrence=_rule(every_minutes))


def get(task_id: str) -> Optional[Dict[str, Any]]:
    row = schedules.get(task_id)
    return row if row and row.get("kind") == KIND else None


def running() -> List[Dict[str, Any]]:
    """The user's tasks that still run or are paused, oldest first."""
    rows = schedules.list_schedules(KIND)
    return [r for r in rows if r.get("status") in ("pending", "paused")]


def pause(task_id: str) -> bool:
    return bool(get(task_id)) and schedules.update(task_id, status="paused")


def resume(task_id: str) -> bool:
    return bool(get(task_id)) and schedules.update(task_id, status="pending")


def set_every(task_id: str, every_minutes: int) -> bool:
    return bool(get(task_id)) and schedules.update(task_id, recurrence=_rule(every_minutes))


def remove(task_id: str) -> bool:
    if not get(task_id) or not schedules.delete(task_id):
        return False
    state_coll = _base.coll(STATE)
    if state_coll is not None:
        state_coll.delete_one({"_id": task_id})
    return True


def state(task_id: str) -> Dict[str, Any]:
    """What the task saw on its last run; {} before its first."""
    coll = _base.coll(STATE)
    row = coll.find_one({"_id": task_id}) if coll is not None else None
    return {k: v for k, v in (row or {}).items() if k not in ("_id", "user_id")}


def save_state(task_id: str, values: Mapping[str, Any]) -> None:
    coll = _base.coll(STATE)
    if coll is not None:
        coll.update_one({"_id": task_id}, {"$set": dict(values)}, upsert=True)
