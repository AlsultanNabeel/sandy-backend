"""Tasks: work Sandy does on her own at its time (`brain/task_runner.py`), set up by talk.

A task is a `sandy_schedules` row of kind «task», so the minute runner claims, fires and
moves it on like any other row. It repeats every N minutes (an RRULE), may be paused
(`status: paused`, never due), and carries what to do in its payload: the user's own words
(`instructions`), a check the code runs first (`probe`: one read tool and its arguments),
what is worth telling (`notify_when`), the tools the model may use, the language, whether it is
urgent, and how its results are emailed (`delivery`, his own choice: `how`). Nothing in it names a field of work: a student's deadlines, a freelancer's new
projects, a shop's stock and a home's budget are the same row with other words.

What it saw last (a fingerprint of the probe, the last result, the failures in a row) is in
`sandy_task_state`, one row per task under its user, removed with the task, as are its
results (`notify.forget_task`).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from app.blocks import _base, schedules

KIND = "task"
STATE = "sandy_task_state"
SWITCH = "tasks"
# What a task's check may run, and all its model may use: a task only reads and tells. Nothing
# that writes, rings or switches a device («remind me two days before» is its own message,
# through its channels, never a reminder).
READ_TOOLS = ("web_search", "recall", "summarize", "weather", "device_state")
ALLOWED = READ_TOOLS


# How its results are emailed, as he said it: on every change, a summary once a day at his hour,
# or at most once every N hours. With nothing said, at most once an hour; Sandy never chooses.
INSTANT, DAILY, EVERY = "instant", "daily", "every"
DEFAULT_DELIVERY = {"mode": EVERY, "hours": 1}
MAX_HOURS = 168
_AT = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def clean_delivery(mode: Any = None, hours: Any = None, at: Any = None) -> Dict[str, Any]:
    """The delivery from his words; the default with none. ValueError when it cannot be read."""
    if not mode:
        return dict(DEFAULT_DELIVERY)
    if mode == INSTANT:
        return {"mode": INSTANT}
    if mode == DAILY:
        found = _AT.match(str(at or "").strip())
        if not found:
            raise ValueError("a daily summary needs its hour, HH:MM")
        return {"mode": DAILY, "at": f"{int(found[1]):02d}:{found[2]}"}
    if mode == EVERY:
        try:
            n = int(hours if hours is not None else 1)
        except (TypeError, ValueError):
            raise ValueError("every needs a number of hours") from None
        if not 1 <= n <= MAX_HOURS:
            raise ValueError(f"every is 1 to {MAX_HOURS} hours")
        return {"mode": EVERY, "hours": n}
    raise ValueError(f"the way is one of {INSTANT}, {DAILY}, {EVERY}")


def how(row: Mapping[str, Any]) -> Dict[str, Any]:
    """How this task's results are emailed (the default for a row saved before it was asked)."""
    saved = (row.get("payload") or {}).get("delivery") or {}
    try:
        return clean_delivery(saved.get("mode"), saved.get("hours"), saved.get("at"))
    except ValueError:
        return dict(DEFAULT_DELIVERY)


def set_delivery(task_id: str, delivery: Mapping[str, Any]) -> bool:
    row = get(task_id)
    if not row:
        return False
    return schedules.update(task_id, payload={**(row.get("payload") or {}), "delivery": dict(delivery)})


def _rule(every_minutes: int) -> str:
    minutes = int(every_minutes)
    if minutes <= 0:
        raise ValueError("every_minutes must be above zero")
    return f"FREQ=MINUTELY;INTERVAL={minutes}"


def every_minutes(row: Mapping[str, Any]) -> int:
    """How many minutes apart it runs (0 for a row with no interval)."""
    rule = str(row.get("recurrence") or "")
    return int(rule.rsplit("INTERVAL=", 1)[-1]) if "INTERVAL=" in rule else 0


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
    """Runs again, its failures counted from zero: one stopped by them is not stopped again by
    the next one."""
    if not get(task_id) or not schedules.update(task_id, status="pending"):
        return False
    save_state(task_id, {"failures": 0, "last_error": ""})
    return True


def set_every(task_id: str, every_minutes: int) -> bool:
    return bool(get(task_id)) and schedules.update(task_id, recurrence=_rule(every_minutes))


def edit(task_id: str, *, title: Optional[str] = None, instructions: Optional[str] = None,
         probe: Optional[Mapping[str, Any]] = None, every: Optional[int] = None,
         delivery: Optional[Mapping[str, Any]] = None, language: Optional[str] = None) -> bool:
    """One change of a task, whatever asks for it (talk, a call, the Tasks screen): what is not
    given stays. New words or a new check forget what it saw, so the next run starts afresh.
    The caller has checked the values (`probe` reads, `delivery` is clean)."""
    row = get(task_id)
    if not row:
        return False
    payload = dict(row.get("payload") or {})
    if instructions is not None:
        payload["instructions"] = instructions
    if probe is not None:
        payload["probe"] = dict(probe)
        payload["tools"] = list(dict.fromkeys(
            [probe["tool"], *[t for t in payload.get("tools") or [] if t in ALLOWED]]))
    if delivery is not None:
        payload["delivery"] = dict(delivery)
    if language is not None:
        payload["lang"] = language
    changed = schedules.update(task_id, text=title or None, payload=payload,
                               recurrence=_rule(every) if every else None)
    if instructions is not None or probe is not None:
        save_state(task_id, {"fingerprint": None, "last_seen": None})
    return bool(changed)


def remove(task_id: str) -> bool:
    if not get(task_id) or not schedules.delete(task_id):
        return False
    state_coll = _base.coll(STATE)
    if state_coll is not None:
        state_coll.delete_one({"_id": task_id})
    from app import notify
    notify.forget_task(task_id)
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
