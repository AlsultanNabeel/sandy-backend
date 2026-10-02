"""Habit commitment: the days every habit due that day was kept.

A day counts when the user kept all the habits scheduled for it (a habit's `data.days`,
1 = Sunday … 7 = Saturday, none = every day; a habit is due only from the day it was
added; archived ones are left out). A day with nothing scheduled neither counts nor
breaks a run. «Days committed» is how many such days there were; the streak is how
many came in a row, up to today.

Today is still open, so the answer comes in two parts: up to yesterday (`base_*`),
and with today added when today is already complete. The app keeps the base and adds
today itself, so ticking the last habit shows at once, offline too, and the two agree.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

from app.blocks import _base, items
from app.utils.time import USER_TZ


def weekday(day: date) -> int:
    """1 = Sunday … 7 = Saturday (the app's numbering)."""
    return (day.weekday() + 1) % 7 + 1


def _local_day(value: Any) -> Optional[date]:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(USER_TZ).date()


def due_on(day: date, habits: List[Dict[str, Any]]) -> List[str]:
    """The ids of the habits due that day."""
    out = []
    for h in habits:
        added = _local_day(h.get("created_at"))
        days = (h.get("data") or {}).get("days") or []
        if (added is None or added <= day) and (not days or weekday(day) in days):
            out.append(h["id"])
    return out


def progress(now: Optional[datetime] = None) -> Dict[str, Any]:
    """{committed_days, streak, base_committed, base_streak} for the current user."""
    today = (now or datetime.now(timezone.utc)).astimezone(USER_TZ).date()
    habits = [h for h in items.list_items("habits", done=False, limit=500)
              if not (h.get("data") or {}).get("archived")]
    zero = {"committed_days": 0, "streak": 0, "base_committed": 0, "base_streak": 0}
    if not habits:
        return zero
    kept: Dict[date, Set[str]] = {}
    # Every check-in ever (list_entries caps its page; this needs them all, small fields only).
    handle = _base.coll(_base.ENTRIES)
    rows = handle.find({"kind": "habit"}, {"_id": 0, "data": 1}) if handle is not None else []
    for e in rows:
        data = e.get("data") or {}
        try:
            day = date.fromisoformat(str(data.get("date") or ""))
        except ValueError:
            continue
        kept.setdefault(day, set()).add(str(data.get("habit_item_id") or ""))

    first = min((_local_day(h.get("created_at")) or today) for h in habits)

    def complete(day: date) -> Optional[bool]:
        """None when nothing was due that day."""
        due = due_on(day, habits)
        return None if not due else set(due) <= kept.get(day, set())

    base_committed = sum(1 for i in range((today - first).days)
                         if complete(first + timedelta(days=i)))
    base_streak = 0
    day = today - timedelta(days=1)
    while day >= first:
        state = complete(day)
        if state is False:
            break
        if state:
            base_streak += 1
        day -= timedelta(days=1)
    today_done = bool(complete(today))
    return {"committed_days": base_committed + today_done,
            "streak": base_streak + today_done,
            "base_committed": base_committed, "base_streak": base_streak}
