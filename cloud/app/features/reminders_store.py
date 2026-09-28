"""Native reminder store (sandy_reminders).

The phone reads /api/reminders and schedules local notifications (repeating ones
from their RRULE); there is no server-side push poller. Recurring reminders are
advanced on read. add/update return {"success": bool, "error": ...}.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.utils.tenant_db import scoped
from app.utils.time import USER_TZ
from app.db import configure, get_db

logger = logging.getLogger(__name__)

_COLL = "sandy_reminders"

# A dyno restart can skip a tick or two; older than this is dropped.
_LOOKBACK_MIN = 15

_UNSENT_STATES = ("pending", "sending", "failed")


def init_reminders_store(mongo_db) -> None:
    configure(mongo_db)
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index(
            [("user_id", 1), ("send_state", 1), ("remind_at", 1)], background=True
        )
        logger.info("[RemindersStore] ready")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[RemindersStore] index skipped: {e}")


def is_available() -> bool:
    return get_db() is not None


def _coll():
    return scoped(get_db(), _COLL)


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=USER_TZ) if dt.tzinfo is None else dt
    except Exception:
        return None


def _to_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def _as_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Mongo returns naive datetimes that are actually UTC."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _normalize(doc: Dict[str, Any]) -> Dict[str, Any]:
    remind_at = _as_aware_utc(doc.get("remind_at"))
    return {
        "id": doc.get("_id", ""),
        "text": doc.get("text", "") or "",
        "remind_at": remind_at.astimezone(USER_TZ).isoformat() if remind_at else "",
        "is_recurring": bool(doc.get("recurrence")),
        "recurrence": doc.get("recurrence", "") or "",
        "task_id": doc.get("linked_task_id", "") or "",
        "kind": doc.get("kind", "reminder") or "reminder",
        "send_state": doc.get("send_state", "pending"),
        "note": doc.get("note", "") or "",
    }


# ─── Reads ────────────────────────────────────────────────────────────────────

def _next_occurrence(recurrence: str, first: datetime, after: datetime) -> Optional[datetime]:
    """First occurrence of the RRULE (anchored at ``first``) strictly after ``after``; None when it ended."""
    from dateutil.rrule import rrulestr

    # Anchored in local time so "every day at 8" survives DST changes.
    start = first.astimezone(USER_TZ)
    rule = rrulestr(recurrence.removeprefix("RRULE:"), dtstart=start)
    nxt = rule.after(after.astimezone(USER_TZ), inc=False)
    return nxt.astimezone(timezone.utc) if nxt else None


def _series_anchor(doc: Dict[str, Any]) -> Optional[datetime]:
    """The RRULE anchor: `series_at` while a snooze has moved `remind_at`, else `remind_at`."""
    return _as_aware_utc(doc.get("series_at")) or _as_aware_utc(doc.get("remind_at"))


def _advance_recurring(coll, now: datetime) -> None:
    """Roll every past-due recurring reminder to its next time (done on read)."""
    cutoff = now - timedelta(minutes=_LOOKBACK_MIN)
    # `send_state` leads the filter so the (user_id, send_state, remind_at) index serves it.
    for doc in coll.find({"send_state": {"$in": list(_UNSENT_STATES)},
                          "recurrence": {"$nin": ["", None]},
                          "remind_at": {"$lt": cutoff}}).limit(200):
        first = _series_anchor(doc)
        try:
            nxt = _next_occurrence(doc["recurrence"], first, cutoff) if first else None
        except (ValueError, TypeError) as exc:
            logger.warning("[RemindersStore] bad recurrence on %s: %s", doc.get("_id"), exc)
            continue
        if nxt is None:
            coll.update_one({"_id": doc["_id"]}, {"$set": {"send_state": "sent"}})
        else:
            coll.update_one({"_id": doc["_id"]},
                            {"$set": {"remind_at": nxt, "send_state": "pending",
                                      "series_at": None}})


def load_reminders(max_results: int = 50) -> List[Dict[str, Any]]:
    """Upcoming unsent reminders, soonest first."""
    try:
        coll = _coll()
        if coll is None:
            return []
        _advance_recurring(coll, datetime.now(timezone.utc))
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_LOOKBACK_MIN)
        docs = (
            coll.find(
                {
                    "send_state": {"$in": list(_UNSENT_STATES)},
                    "remind_at": {"$gte": cutoff},
                }
            )
            .sort("remind_at", 1)
            .limit(max_results)
        )
        return [_normalize(d) for d in docs]
    except Exception as e:
        logger.warning(f"[RemindersStore] load failed: {e}")
        return []


# ─── Writes ───────────────────────────────────────────────────────────────────

def add_reminder(
    text: str,
    remind_at_iso: str,
    recurrence: str = "",
    linked_task_id: str = "",
    kind: str = "reminder",
    parent_summary: str = "",
    note: str = "",
) -> Dict[str, Any]:
    try:
        coll = _coll()
        if coll is None:
            return {"success": False, "error": "no_store"}

        text = str(text or "").strip()
        if not text:
            return {"success": False, "error": "empty_text"}

        remind_dt = _parse_iso(remind_at_iso)
        if remind_dt is None:
            return {"success": False, "error": "bad_datetime"}
        if remind_dt <= datetime.now(USER_TZ):
            return {"success": False, "error": "past_datetime"}

        doc = {
            "_id": uuid.uuid4().hex,
            "text": text,
            "remind_at": _to_utc(remind_dt),
            "recurrence": str(recurrence or "").strip(),
            "kind": kind or "reminder",
            "parent_summary": str(parent_summary or "").strip(),
            "note": str(note or "").strip(),
            "linked_task_id": str(linked_task_id or "").strip(),
            "send_state": "pending",
            "created_at": datetime.now(timezone.utc),
            "sent_at": None,
            "last_error": "",
        }
        coll.insert_one(doc)
        logger.info(f"[RemindersStore] reminder created: {text} @ {remind_at_iso}")
        return {"success": True, "id": doc["_id"]}
    except Exception as e:
        logger.warning(f"[RemindersStore] create failed: {e}")
        return {"success": False, "error": str(e)}


def update_reminder(
    reminder_id: str,
    title: str = "",
    start_iso: str = "",
    recurrence: Optional[str] = None,
    note: Optional[str] = None,
) -> Dict[str, Any]:
    """Empty title/start_iso means "leave unchanged"; recurrence/note=None too."""
    try:
        coll = _coll()
        if coll is None or not reminder_id:
            return {"success": False, "error": "missing"}

        updates: Dict[str, Any] = {}
        if title:
            updates["text"] = str(title).strip()
        if start_iso:
            new_dt = _parse_iso(start_iso)
            if new_dt is None:
                return {"success": False, "error": "bad_datetime"}
            if new_dt <= datetime.now(USER_TZ):
                return {"success": False, "error": "past_datetime"}
            updates["remind_at"] = _to_utc(new_dt)
            updates["send_state"] = "pending"
            updates["sent_at"] = None
            # An explicit new time is the series now; drop any snooze anchor.
            updates["series_at"] = None
        if recurrence is not None:
            updates["recurrence"] = str(recurrence).strip()
        if note is not None:
            updates["note"] = str(note).strip()
        if not updates:
            return {"success": False, "error": "nothing_to_update"}

        r = coll.update_one({"_id": reminder_id}, {"$set": updates})
        if r.matched_count == 0:
            return {"success": False, "error": "not_found"}
        return {"success": True}
    except Exception as e:
        logger.warning(f"[RemindersStore] update failed: {e}")
        return {"success": False, "error": str(e)}


# ─── Acting on a reminder that just fired (phone notification actions) ───────

# Snooze bounds in minutes.
_MIN_SNOOZE_MIN = 1
_MAX_SNOOZE_MIN = 7 * 24 * 60


def snooze_reminder(reminder_id: str, minutes: int = 10) -> Dict[str, Any]:
    """Re-arm ``minutes`` from now; a recurring series still returns to its own schedule."""
    try:
        coll = _coll()
        if coll is None or not reminder_id:
            return {"success": False, "error": "missing"}
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            return {"success": False, "error": "bad_minutes"}
        if not _MIN_SNOOZE_MIN <= minutes <= _MAX_SNOOZE_MIN:
            return {"success": False, "error": "bad_minutes"}

        doc = coll.find_one({"_id": reminder_id})
        if not doc:
            return {"success": False, "error": "not_found"}

        new_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        updates: Dict[str, Any] = {
            "remind_at": new_at,
            "send_state": "pending",
            "sent_at": None,
        }
        # Remember the occurrence being left, once (snoozing twice must not move it).
        if doc.get("recurrence") and doc.get("series_at") is None:
            updates["series_at"] = _as_aware_utc(doc.get("remind_at"))
        coll.update_one({"_id": reminder_id}, {"$set": updates})
        return {
            "success": True,
            "remind_at": new_at.astimezone(USER_TZ).isoformat(),
            "is_recurring": bool(doc.get("recurrence")),
        }
    except Exception as e:
        logger.warning(f"[RemindersStore] snooze failed: {e}")
        return {"success": False, "error": str(e)}


def complete_reminder(reminder_id: str) -> Dict[str, Any]:
    """Mark handled: a one-off retires, a recurring one moves to its next occurrence.

    ``remind_at`` in the result is the next time, or "" when nothing is left.
    """
    try:
        coll = _coll()
        if coll is None or not reminder_id:
            return {"success": False, "error": "missing"}
        doc = coll.find_one({"_id": reminder_id})
        if not doc:
            return {"success": False, "error": "not_found"}

        now = datetime.now(timezone.utc)
        recurrence = str(doc.get("recurrence") or "")
        nxt = None
        if recurrence:
            anchor = _series_anchor(doc)
            current = _as_aware_utc(doc.get("remind_at")) or now
            # Strictly after the dismissed occurrence, so an early "done" skips today.
            after = max(now, current)
            try:
                nxt = _next_occurrence(recurrence, anchor, after) if anchor else None
            except (ValueError, TypeError) as exc:
                logger.warning("[RemindersStore] bad recurrence on %s: %s", reminder_id, exc)
                nxt = None

        if nxt is None:
            coll.update_one({"_id": reminder_id},
                            {"$set": {"send_state": "sent", "sent_at": now}})
            return {"success": True, "remind_at": "", "is_recurring": bool(recurrence)}

        coll.update_one(
            {"_id": reminder_id},
            {"$set": {"remind_at": nxt, "send_state": "pending",
                      "series_at": None, "sent_at": None}},
        )
        return {
            "success": True,
            "remind_at": nxt.astimezone(USER_TZ).isoformat(),
            "is_recurring": True,
        }
    except Exception as e:
        logger.warning(f"[RemindersStore] complete failed: {e}")
        return {"success": False, "error": str(e)}


def delete_reminder(reminder_id: str) -> bool:
    try:
        coll = _coll()
        if coll is None or not reminder_id:
            return False
        return coll.delete_one({"_id": reminder_id}).deleted_count > 0
    except Exception as e:
        logger.warning(f"[RemindersStore] delete failed: {e}")
        return False


def delete_sandy_reminder_by_task_id(task_id: str) -> int:
    try:
        coll = _coll()
        if coll is None or not task_id:
            return 0
        return coll.delete_many({"linked_task_id": task_id}).deleted_count
    except Exception as e:
        logger.warning(f"[RemindersStore] delete by task failed: {e}")
        return 0


def delete_all_sandy_reminders() -> int:
    try:
        coll = _coll()
        if coll is None:
            return 0
        r = coll.delete_many({})
        logger.info(f"[RemindersStore] deleted all reminders: {r.deleted_count}")
        return r.deleted_count
    except Exception as e:
        logger.warning(f"[RemindersStore] delete all failed: {e}")
        return 0
