"""Native reminder store — MongoDB, no external provider.

Replaces the Google Calendar "invisible event" hack: reminders used to be
calendar events with private props that a poller scraped back out. Now they
are plain Mongo documents and the same poller contract reads them directly.

Collection: sandy_reminders
  {_id, text, remind_at (datetime UTC), recurrence ("RRULE:FREQ=..." or ""),
   kind ("reminder" | "event_followup"), parent_summary, note (""),
   linked_task_id, send_state ("pending" | "sending" | "sent" | "failed"),
   created_at, sent_at, last_error}

Return contracts mirror the old google_calendar functions so the executor
handlers keep working with an import swap:
  add_reminder / update_reminder → {"success": bool, "error": ...}

The frontend polls /api/reminders every minute to surface due reminders, so the
backend stores and serves them only — there is no server-side push poller.

Tenant isolation is enforced by the scoped() layer: _coll() returns None when
there's no Mongo handle or no active tenant, so each "coll is None" guard fails
closed, and user_id is injected on every read/write automatically.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.utils.tenant_db import scoped
from app.utils.time import USER_TZ

_COLL = "sandy_reminders"
_mongo_db = None

# How far back the due-check looks. A dyno restart can skip a minute-cron tick
# or two; anything older than this window is stale enough to drop silently.
_LOOKBACK_MIN = 15


def init_reminders_store(mongo_db) -> None:
    """يُستدعى مرّة عند الإقلاع."""
    global _mongo_db
    _mongo_db = mongo_db
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index(
            [("user_id", 1), ("send_state", 1), ("remind_at", 1)], background=True
        )
        print("[RemindersStore] ready")
    except Exception as e:  # noqa: BLE001
        print(f"[RemindersStore] index skipped: {e}")


def is_available() -> bool:
    return _mongo_db is not None


def _coll():
    """Tenant-scoped collection (request path). None when no db / no tenant."""
    return scoped(_mongo_db, _COLL)


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=USER_TZ) if dt.tzinfo is None else dt
    except Exception:
        return None


def _to_utc(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc)


def _as_aware_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Mongo returns naive datetimes that are actually UTC — fix that."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _normalize(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Mongo doc → the dict shape the handlers and the web UI already expect."""
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

def load_reminders(max_results: int = 50) -> List[Dict[str, Any]]:
    """Upcoming (not yet sent) reminders, soonest first."""
    try:
        coll = _coll()
        if coll is None:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=_LOOKBACK_MIN)
        docs = (
            coll.find(
                {
                    "send_state": {"$in": ["pending", "sending", "failed"]},
                    "remind_at": {"$gte": cutoff},
                }
            )
            .sort("remind_at", 1)
            .limit(max_results)
        )
        return [_normalize(d) for d in docs]
    except Exception as e:
        print(f"[RemindersStore] load failed: {e}")
        return []


# Same data, the name the web API used against Google Calendar.
def list_sandy_reminders(max_results: int = 50) -> List[Dict[str, Any]]:
    return load_reminders(max_results=max_results)


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
        print(f"[RemindersStore] reminder created: {text} @ {remind_at_iso}")
        return {"success": True, "id": doc["_id"]}
    except Exception as e:
        print(f"[RemindersStore] create failed: {e}")
        return {"success": False, "error": str(e)}


def update_reminder(
    reminder_id: str,
    title: str = "",
    start_iso: str = "",
    recurrence: Optional[str] = None,
) -> Dict[str, Any]:
    """Empty title/start_iso means "leave unchanged"; recurrence=None too."""
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
        if recurrence is not None:
            updates["recurrence"] = str(recurrence).strip()
        if not updates:
            return {"success": False, "error": "nothing_to_update"}

        r = coll.update_one({"_id": reminder_id}, {"$set": updates})
        if r.matched_count == 0:
            return {"success": False, "error": "not_found"}
        return {"success": True}
    except Exception as e:
        print(f"[RemindersStore] update failed: {e}")
        return {"success": False, "error": str(e)}


def snooze_reminder(reminder_id: str, minutes: int = 30) -> Dict[str, Any]:
    """Push a reminder forward from now (works on sent ones too — that's the point)."""
    try:
        coll = _coll()
        if coll is None or not reminder_id:
            return {"success": False, "error": "missing"}
        new_dt = datetime.now(USER_TZ) + timedelta(minutes=max(1, int(minutes)))
        r = coll.update_one(
            {"_id": reminder_id},
            {
                "$set": {
                    "remind_at": _to_utc(new_dt),
                    "send_state": "pending",
                    "sent_at": None,
                }
            },
        )
        if r.matched_count == 0:
            return {"success": False, "error": "not_found"}
        return {"success": True, "new_iso": new_dt.isoformat()}
    except Exception as e:
        print(f"[RemindersStore] snooze failed: {e}")
        return {"success": False, "error": str(e)}


def complete_reminder(reminder_id: str) -> bool:
    """Owner tapped "done" — close it out, recurring or not."""
    try:
        coll = _coll()
        if coll is None or not reminder_id:
            return False
        r = coll.update_one(
            {"_id": reminder_id},
            {
                "$set": {
                    "send_state": "sent",
                    "recurrence": "",
                    "sent_at": datetime.now(timezone.utc),
                }
            },
        )
        return r.matched_count > 0
    except Exception as e:
        print(f"[RemindersStore] complete failed: {e}")
        return False


def delete_reminder(reminder_id: str) -> bool:
    try:
        coll = _coll()
        if coll is None or not reminder_id:
            return False
        return coll.delete_one({"_id": reminder_id}).deleted_count > 0
    except Exception as e:
        print(f"[RemindersStore] delete failed: {e}")
        return False


def delete_sandy_reminder_by_task_id(task_id: str) -> int:
    try:
        coll = _coll()
        if coll is None or not task_id:
            return 0
        return coll.delete_many({"linked_task_id": task_id}).deleted_count
    except Exception as e:
        print(f"[RemindersStore] delete by task failed: {e}")
        return 0


def delete_all_sandy_reminders() -> int:
    try:
        coll = _coll()
        if coll is None:
            return 0
        r = coll.delete_many({})
        print(f"[RemindersStore] deleted all reminders: {r.deleted_count}")
        return r.deleted_count
    except Exception as e:
        print(f"[RemindersStore] delete all failed: {e}")
        return 0
