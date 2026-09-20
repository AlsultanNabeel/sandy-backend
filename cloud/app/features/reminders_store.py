"""Native reminder store — MongoDB, no external provider.

Replaces the Google Calendar "invisible event" hack: reminders used to be
calendar events with private props that a poller scraped back out. Now they
are plain Mongo documents and the same poller contract reads them directly.

Collection: sandy_reminders
  {_id, text, remind_at (datetime UTC), series_at (datetime UTC | None),
   recurrence ("RRULE:FREQ=..." or ""),
   kind ("reminder" | "event_followup"), parent_summary, note (""),
   linked_task_id, send_state ("pending" | "sending" | "sent" | "failed"),
   created_at, sent_at, last_error}

Return contracts mirror the old google_calendar functions so the executor
handlers keep working with an import swap:
  add_reminder / update_reminder → {"success": bool, "error": ...}

The phone reads /api/reminders and schedules each one as a local notification
(repeating ones from their RRULE), so the backend stores and serves them only —
there is no server-side push poller.

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
from app.db import configure, get_db
import logging

logger = logging.getLogger(__name__)

_COLL = "sandy_reminders"

# How far back the due-check looks. A dyno restart can skip a minute-cron tick
# or two; anything older than this window is stale enough to drop silently.
_LOOKBACK_MIN = 15

# Every state a reminder can be in before it has fired for good.
_UNSENT_STATES = ("pending", "sending", "failed")


def init_reminders_store(mongo_db) -> None:
    """يُستدعى مرّة عند الإقلاع."""
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
    """Tenant-scoped collection (request path). None when no db / no tenant."""
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

def _next_occurrence(recurrence: str, first: datetime, after: datetime) -> Optional[datetime]:
    """The first occurrence of ``recurrence`` (an RRULE anchored at ``first``)
    strictly after ``after``; None when the rule has ended (UNTIL/COUNT)."""
    from dateutil.rrule import rrulestr

    # Anchored in the user's zone, so "every day at 8" stays at 8 local time
    # across a daylight-saving change instead of drifting by an hour in UTC.
    start = first.astimezone(USER_TZ)
    rule = rrulestr(recurrence.removeprefix("RRULE:"), dtstart=start)
    nxt = rule.after(after.astimezone(USER_TZ), inc=False)
    return nxt.astimezone(timezone.utc) if nxt else None


def _series_anchor(doc: Dict[str, Any]) -> Optional[datetime]:
    """The time the RRULE is anchored at — `series_at` when a snooze moved the
    reminder off its own occurrence, `remind_at` otherwise.

    A snooze rewrites `remind_at`, and the rule is anchored at it, so without
    this a daily reminder snoozed ten minutes would drift ten minutes later
    every single day. `series_at` remembers the occurrence the snooze left,
    and is cleared again the moment the series rolls forward on its own.
    """
    return _as_aware_utc(doc.get("series_at")) or _as_aware_utc(doc.get("remind_at"))


def _advance_recurring(coll, now: datetime) -> None:
    """Move every recurring reminder whose time has passed to its next time.

    Nothing advanced them: the phone schedules a notification from `remind_at`,
    and once that was more than `_LOOKBACK_MIN` in the past the reminder fell
    out of every list — a daily reminder rang once and then vanished. Done on
    read, so the next time anyone looks (the app, Sandy) the list is current.
    """
    cutoff = now - timedelta(minutes=_LOOKBACK_MIN)
    # Recurring reminders are few; this touches only the ones that are due.
    # `send_state` leads the filter so the (user_id, send_state, remind_at)
    # index serves it — without it every read walked the tenant's whole
    # history of fired one-shot reminders, which is never pruned. A rule that
    # has ended is marked "sent" below and must not be re-evaluated each read.
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
            # Back on its own occurrence, so any snooze anchor is spent.
            coll.update_one({"_id": doc["_id"]},
                            {"$set": {"remind_at": nxt, "send_state": "pending",
                                      "series_at": None}})


def load_reminders(max_results: int = 50) -> List[Dict[str, Any]]:
    """Upcoming (not yet sent) reminders, soonest first."""
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
            # An explicit new time *is* the series now — a leftover snooze
            # anchor would drag the rule back to the old one.
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


# ─── Acting on a reminder that just fired ─────────────────────────────────────
#
# Snooze and done are verbs, not field edits: `update_reminder` would happily
# express either one, but the caller would then have to know that a recurring
# reminder needs its rule re-evaluated — and the notification action on the
# phone, which is where these are used, has no business knowing that.

# Bounds for a snooze, in minutes. Under a minute is a no-op the user cannot
# see; past a week it is a new reminder, not a snooze.
_MIN_SNOOZE_MIN = 1
_MAX_SNOOZE_MIN = 7 * 24 * 60


def snooze_reminder(reminder_id: str, minutes: int = 10) -> Dict[str, Any]:
    """Re-arm a reminder ``minutes`` from now, leaving its recurrence intact.

    The recurring case is the interesting one: the reminder rings again shortly,
    and the series still rolls to *its own* next occurrence afterwards — a daily
    eight o'clock snoozed by ten minutes is back at eight tomorrow, not 8:10.
    """
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
        # Remember the occurrence being left, once — snoozing twice must not
        # move the anchor along with it.
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
    """Mark a reminder handled — it stops firing.

    A one-off retires for good. A recurring one loses only *this* occurrence and
    moves to the next, so "done" on today's eight o'clock still leaves
    tomorrow's. ``remind_at`` in the result is the next time, or empty when
    there is nothing left to ring (a one-off, or a rule that has run out).
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
            # Strictly after the occurrence being dismissed, so tapping "done"
            # early skips today rather than handing today's back.
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
