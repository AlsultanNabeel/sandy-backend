"""Once-a-minute runner for due `sandy_schedules` rows (§2.12): everything that fires.

Each due row is claimed with a compare-and-set on (status "pending", its fire_at):
a one-off moves to "sent", a recurring one to its next RRULE time. Only the
worker whose update matched fires it, so two workers or two dynos never fire
the same row twice. What firing means per kind:

  reminder         APNs when configured (the phone also rings it locally from
                   GET /api/schedules); stale by > 15 min: no push, still settled.
  scene            a scene's timed revert (`scene_store.apply_scene` writes it), sent
                   through `scene_store._actuate`; a miss retries a minute later, up to
                   MAX_TIMER_TRIES.
  daily_nudge,
  summary_nudge    push text only; "failed" when no device took it.
  message_to_future_self  not here: delivered into the next chat reply (`brain/future.py`).

A row copied in by scripts/migrate_to_blocks.py that is more than LOOKBACK_MIN
late is settled without firing: its old store already fired it, and replaying a
scene revert hours later would switch someone's lights for no reason.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any, Dict, List, Optional, Tuple

from dateutil.rrule import rrulestr

from app.blocks import _base, schedules
from app.features import notify_prefs, push_tokens_store
from app.services import apns
from app.utils.time import USER_TZ
from app.utils.user_profiles import active_user_profile_context

logger = logging.getLogger(__name__)

RUNNABLE = ("reminder", "scene", "daily_nudge", "summary_nudge")
PUSH_TITLE = "ساندي"
# A reminder this late is not pushed: the phone already rang it, or it is stale news.
LOOKBACK_MIN = 15
MAX_PER_TICK = 50

_started = False
_scheduler = None


def _due_query(now: datetime) -> Dict[str, Any]:
    return {"status": "pending", "kind": {"$in": list(RUNNABLE)}, "fire_at": {"$lte": now}}


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _profile_for(uid: str) -> dict:
    return {"chat_id": uid, "user_id": uid, "name": "", "relation": "user",
            "tone": "casual", "permissions": "all"}


def users_with_due(mongo_db, now: Optional[datetime] = None) -> List[str]:
    """Owners with a due row (raw cross-tenant read; only ids leave)."""
    if mongo_db is None:
        return []
    try:
        ids = mongo_db[_base.SCHEDULES].distinct(
            "user_id", _due_query(now or datetime.now(timezone.utc)))
    except Exception as exc:  # noqa: BLE001 — one failed scan waits for the next tick
        logger.warning("[schedules] due scan failed: %s", exc)
        return []
    return [str(u) for u in ids if u]


def next_occurrence(recurrence: str, first: datetime, after: datetime) -> Optional[datetime]:
    """First occurrence of the RRULE (anchored at ``first``, the series' start,
    `schedules.series_anchor`) strictly after ``after``; None when it ended."""
    # Anchored in local time so "every day at 8" survives DST changes.
    start = first.astimezone(USER_TZ)
    rule = rrulestr(recurrence.removeprefix("RRULE:"), dtstart=start)
    nxt = rule.after(after.astimezone(USER_TZ), inc=False)
    return nxt.astimezone(timezone.utc) if nxt else None


def _next_time(doc: Dict[str, Any], now: datetime) -> Optional[datetime]:
    rule = str(doc.get("recurrence") or "")
    if not rule:
        return None
    try:
        return next_occurrence(rule, schedules.series_anchor(doc), now)
    except (ValueError, TypeError) as exc:
        logger.warning("[schedules] bad recurrence on %s: %s", doc.get("_id"), exc)
        return None


def _claim(coll, doc: Dict[str, Any], now: datetime) -> Tuple[bool, Optional[datetime]]:
    """(won, next fire time or None) — the atomic claim."""
    nxt = _next_time(doc, now)
    change = {"fire_at": nxt} if nxt else {"status": "sent"}
    if doc.get("recurrence") and not doc.get("series_start"):
        # Saved before the start was kept: its count runs from this ring on.
        change["series_start"] = schedules.series_start(doc["fire_at"])
    res = coll.update_one({"_id": doc["_id"], "status": "pending", "fire_at": doc["fire_at"]},
                          {"$set": {**change, "fired_at": now}})
    return res.modified_count == 1, nxt


def follow_zone(uid: str, old_zone: tzinfo, now: Optional[datetime] = None) -> int:
    """The user's clock moved (`utils/time.note_zone`): every pending repeat is set to its next
    time on the new clock, by the same compare-and-set as a claim. A one-off keeps its moment.
    A row saved before its series' start was kept is anchored first on the clock it was set on."""
    now = now or datetime.now(timezone.utc)
    moved = 0
    try:
        with active_user_profile_context(_profile_for(uid)):
            coll = _base.coll(_base.SCHEDULES)
            if coll is None:
                return 0
            for doc in list(coll.find({"status": "pending", "recurrence": {"$nin": ["", None]},
                                       "fire_at": {"$gt": now}})):
                start = doc.get("series_start") or _aware(doc["fire_at"]).astimezone(
                    old_zone).replace(tzinfo=None).isoformat(timespec="seconds")
                nxt = _next_time({**doc, "series_start": start}, now)
                if nxt is None:
                    continue
                res = coll.update_one({"_id": doc["_id"], "status": "pending", "fire_at": doc["fire_at"]},
                                      {"$set": {"fire_at": nxt, "series_start": start}})
                moved += res.modified_count
    except Exception as exc:  # noqa: BLE001 — a request is never failed by this; the rows keep their times
        logger.warning("[schedules] zone follow for %s failed: %s", uid, exc)
    return moved


def _push(uid: str, text: str, data: Dict[str, Any], silent: bool = False) -> Tuple[int, int]:
    """(devices tried, devices that took it)."""
    tried = took = 0
    for token in push_tokens_store.tokens_for_user(uid):
        tried += 1
        ok, status = apns.send(token, PUSH_TITLE, text, data=data, silent=silent)
        if ok:
            took += 1
        elif status == "gone":
            push_tokens_store.unregister_token(token)
    return tried, took


def _fire(doc: Dict[str, Any], uid: str, now: datetime) -> Tuple[bool, str]:
    """(ok, error). Raises only on a bug; the caller marks that "failed"."""
    kind, text = doc["kind"], str(doc.get("text") or "")
    data = {"kind": kind, "schedule_id": doc["_id"]}
    late = _aware(doc["fire_at"]) < now - timedelta(minutes=LOOKBACK_MIN)
    if doc.get("migrated_from") and late:
        return True, ""
    if kind == "scene":
        # Import here: scene_store pulls in the device/MQTT stack (C9).
        from app.features.scene_store import _actuate
        payload = doc.get("payload") or {}
        r = _actuate([{"device": payload.get("device", ""), "value": payload.get("value", "")}])
        return (True, "") if r["sent"] else (False, "device missed")
    if not apns.is_configured():
        # A reminder still rings on the phone; a push-only nudge reached no one.
        return (True, "") if kind == "reminder" else (False, "apns not configured")
    if kind == "reminder" and late:
        return True, ""
    # The user's switches: a kind turned off is settled without a push; quiet hours push silently.
    wanted, silent = notify_prefs.push_rule(uid, kind, now)
    if not wanted:
        return True, ""
    tried, took = _push(uid, text, data, silent=silent)
    if took or (kind == "reminder" and not tried):
        return True, ""
    return False, "no device took the push"


def _settle_failure(coll, doc: Dict[str, Any], nxt: Optional[datetime],
                    error: str, now: datetime) -> None:
    if doc["kind"] == "scene":
        # Import here for the same reason as in _fire.
        from app.features.scene_store import MAX_TIMER_TRIES
        tries = int((doc.get("payload") or {}).get("tries") or 0) + 1
        if tries < MAX_TIMER_TRIES:
            coll.update_one({"_id": doc["_id"]}, {"$set": {
                "status": "pending", "fire_at": now + timedelta(minutes=1),
                "payload.tries": tries, "last_error": error}})
            return
    # A recurring row stays armed for its next time; the error is kept on it.
    change = {"last_error": error} if nxt else {"status": "failed", "last_error": error}
    coll.update_one({"_id": doc["_id"]}, {"$set": change})


def run_due(uid: str, now: Optional[datetime] = None) -> Dict[str, int]:
    """Fire the current tenant's due rows; {"fired", "failed"}."""
    now = now or datetime.now(timezone.utc)
    coll = _base.coll(_base.SCHEDULES)
    counts = {"fired": 0, "failed": 0}
    if coll is None:
        return counts
    for doc in list(coll.find(_due_query(now)).sort("fire_at", 1).limit(MAX_PER_TICK)):
        won, nxt = _claim(coll, doc, now)
        if not won:
            continue
        try:
            ok, error = _fire(doc, uid, now)
        except Exception as exc:  # noqa: BLE001 — one row never stops the tick
            logger.exception("[schedules] %s %s raised", doc["kind"], doc["_id"])
            ok, error = False, type(exc).__name__
        if ok:
            counts["fired"] += 1
        else:
            counts["failed"] += 1
            _settle_failure(coll, doc, nxt, error, now)
    return counts


def run_all_due(mongo_db) -> int:
    """One tick over every tenant with something due; returns how many fired."""
    total = 0
    for uid in users_with_due(mongo_db):
        try:
            with active_user_profile_context(_profile_for(uid)):
                total += run_due(uid)["fired"]
        except Exception as exc:  # noqa: BLE001 — one tenant never stops the tick
            logger.warning("[schedules] user %s failed: %s", uid, exc)
    return total


def start_schedule_runner(mongo_db) -> bool:
    global _started, _scheduler
    if _started:
        return True
    if mongo_db is None:
        return False
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(timezone="UTC")
        _scheduler.add_job(
            run_all_due, "interval", minutes=1, args=[mongo_db],
            id="block_schedules", replace_existing=True,
            max_instances=1, coalesce=True, misfire_grace_time=120,
        )
        _scheduler.start()
        _started = True
        logger.info("[schedules] started — checking sandy_schedules every minute")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("[schedules] failed to start: %s", exc)
        return False
