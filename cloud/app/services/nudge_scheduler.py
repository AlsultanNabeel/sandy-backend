"""Daily-nudge push scheduler; runs only when APNs is configured.

Every quarter hour (zones sit on the hour, the half and the quarter) it sends the nudge to
each user whose own clock is in the eight o'clock hour, once per local day: an atomic
per-user, per-day Mongo lock makes one worker on one dyno send it. Their quiet hours are
read inside their own context, so on their clock.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from app.services import apns
from app.utils.time import USER_TZ
from app.utils.user_profiles import active_user_profile_context

logger = logging.getLogger(__name__)

_SEND_HOUR = 8  # local morning
_LOCK_COLL = "sandy_nudge_locks"
_started = False
_scheduler = None


def _profile_for(uid: str) -> dict:
    return {"chat_id": uid, "name": "", "relation": "user",
            "tone": "casual", "permissions": "all"}


def _claim_daily_lock(mongo_db, uid: str, day: str) -> bool:
    """Atomically claim this user's send for their local day."""
    coll = mongo_db[_LOCK_COLL] if mongo_db is not None else None
    if coll is None:
        return True  # single-process/dev: no contention
    from pymongo.errors import DuplicateKeyError
    try:
        coll.insert_one({"_id": f"send:{uid}:{day}", "created_at": datetime.now(timezone.utc)})
        return True
    except DuplicateKeyError:
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("[nudge_sched] lock claim for %s failed, skipping: %s", uid, exc)
        return False


def _send_one(mongo_db, uid: str, now: datetime) -> int:
    """Devices that took this user's nudge; runs inside the user's context."""
    from app.api.daily_nudge_api import get_daily_nudge
    from app.features import notify_prefs, push_tokens_store

    local = now.astimezone(USER_TZ)
    if local.hour != _SEND_HOUR or not _claim_daily_lock(mongo_db, uid, local.strftime("%Y-%m-%d")):
        return 0
    wanted, silent = notify_prefs.push_rule(uid, "daily_nudge", now)
    if not wanted:
        return 0
    nudge = get_daily_nudge(mongo_db, uid)
    text = str(nudge.get("text") or "").strip()
    if not text:
        return 0
    data = {"kind": nudge.get("kind", "agenda")}
    if nudge.get("qid"):
        data["qid"] = nudge["qid"]
    delivered = 0
    for token in push_tokens_store.tokens_for_user(uid):
        ok, status = apns.send(token, "ساندي", text, data=data, silent=silent)
        if ok:
            delivered += 1
        elif status == "gone":
            push_tokens_store.unregister_token(token)
    return delivered


def run_daily_send(mongo_db, now: Optional[datetime] = None) -> int:
    """Push the nudge to every user whose morning it is now; returns how many devices took it."""
    from app.features import push_tokens_store

    now = now or datetime.now(timezone.utc)
    delivered = 0
    for uid in push_tokens_store.user_ids_with_tokens():
        try:
            with active_user_profile_context(_profile_for(uid)):
                delivered += _send_one(mongo_db, uid, now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[nudge_sched] user %s failed: %s", uid, exc)
    if delivered:
        logger.info("[nudge_sched] daily send delivered=%d", delivered)
    return delivered


def start_nudge_scheduler(mongo_db) -> bool:
    """Start the morning push job; no-op unless APNs is configured."""
    global _started, _scheduler
    if _started:
        return True
    if not apns.is_configured():
        logger.info("[nudge_sched] APNs not configured — push delivery idle")
        return False

    if mongo_db is not None:
        try:
            mongo_db[_LOCK_COLL].create_index(
                "created_at", expireAfterSeconds=60 * 60 * 24 * 2, background=True
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("[nudge_sched] lock index skipped: %s", exc)

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        _scheduler = BackgroundScheduler(timezone="UTC")
        _scheduler.add_job(
            run_daily_send, "cron", minute="0,15,30,45",
            args=[mongo_db], id="daily_nudge_send", replace_existing=True,
            misfire_grace_time=600, coalesce=True, max_instances=1,
        )
        _scheduler.start()
        _started = True
        logger.info("[nudge_sched] started — morning push at %02d:00 on each user's clock", _SEND_HOUR)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("[nudge_sched] failed to start: %s", exc)
        return False
