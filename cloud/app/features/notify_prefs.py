"""Which notifications a user wants, and their quiet hours (Profile › Notifications).

Kept on `sandy_users.notifications`: {reminders, daily, proactive: bool,
quiet_start, quiet_end: "HH:MM" or ""}. The phone applies them to what it rings
itself; the server applies them to its pushes: a kind switched off is not pushed,
and a push inside the quiet hours arrives silently.
"""

from __future__ import annotations

import re
from datetime import datetime, time
from typing import Any, Dict, Optional, Tuple

from app.db import get_db
from app.utils.time import USER_TZ

# alarm_focus: alarms pass a Focus on the phone (time-sensitive); the phone applies it.
DEFAULTS: Dict[str, Any] = {"reminders": True, "daily": True, "proactive": True,
                            "quiet_start": "", "quiet_end": "", "alarm_focus": False}
# A schedule kind or push → the switch that governs it.
KIND_SWITCH = {"reminder": "reminders", "daily_nudge": "daily", "summary_nudge": "daily"}
_CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _users():
    db = get_db()
    return db["sandy_users"] if db is not None else None


def get(user_id: str) -> Dict[str, Any]:
    coll = _users()
    doc = coll.find_one({"_id": user_id}, {"notifications": 1}) if coll is not None and user_id else None
    saved = (doc or {}).get("notifications") or {}
    return {k: saved.get(k, v) for k, v in DEFAULTS.items()}


def clean(body: Dict[str, Any]) -> Dict[str, Any]:
    """The known fields of a request, checked; raises ValueError on a bad clock."""
    out: Dict[str, Any] = {}
    for key in ("reminders", "daily", "proactive", "alarm_focus"):
        if key in body:
            out[key] = bool(body[key])
    for key in ("quiet_start", "quiet_end"):
        if key in body:
            value = str(body[key] or "")
            if value and not _CLOCK.match(value):
                raise ValueError(key)
            out[key] = value
    return out


def save(user_id: str, changes: Dict[str, Any]) -> Dict[str, Any]:
    coll = _users()
    if coll is not None and user_id and changes:
        coll.update_one({"_id": user_id},
                        {"$set": {f"notifications.{k}": v for k, v in changes.items()}})
    return get(user_id)


def _clock(value: str) -> Optional[time]:
    if not value or not _CLOCK.match(value):
        return None
    h, m = value.split(":")
    return time(int(h), int(m))


def quiet(prefs: Dict[str, Any], at: Optional[datetime] = None) -> bool:
    """Inside the quiet hours (a window may cross midnight, e.g. 23:00–07:00)."""
    start, end = _clock(prefs.get("quiet_start", "")), _clock(prefs.get("quiet_end", ""))
    if start is None or end is None or start == end:
        return False
    now = (at or datetime.now(USER_TZ)).astimezone(USER_TZ).time()
    return start <= now < end if start < end else (now >= start or now < end)


def push_rule(user_id: str, kind: str, at: Optional[datetime] = None) -> Tuple[bool, bool]:
    """(push it?, silently?) for a server push of `kind` to this user now."""
    prefs = get(user_id)
    switch = KIND_SWITCH.get(kind)
    if switch and not prefs.get(switch, True):
        return False, False
    return True, quiet(prefs, at)
