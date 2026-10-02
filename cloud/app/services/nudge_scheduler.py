"""Daily-nudge push scheduler; runs only when APNs is configured.

Each gunicorn worker may start one; an atomic per-day Mongo lock makes only one send.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

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


def _claim_daily_lock(mongo_db) -> bool:
    """Atomically claim today's send so only one worker fans out."""
    coll = mongo_db[_LOCK_COLL] if mongo_db is not None else None
    if coll is None:
        return True  # single-process/dev: no contention
    from pymongo.errors import DuplicateKeyError
    key = f"send:{datetime.now(USER_TZ).strftime('%Y-%m-%d')}"
    try:
        coll.insert_one({"_id": key, "created_at": datetime.now(timezone.utc)})
        return True
    except DuplicateKeyError:
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("[nudge_sched] lock claim failed, skipping: %s", exc)
        return False


def run_daily_send(mongo_db) -> int:
    """Push today's nudge to every user with a device; returns how many were delivered."""
    from app.api.daily_nudge_api import get_daily_nudge
    from app.features import push_tokens_store

    if not _claim_daily_lock(mongo_db):
        logger.info("[nudge_sched] another worker owns today's send; skipping")
        return 0

    from app.features import notify_prefs

    delivered = 0
    for uid in push_tokens_store.user_ids_with_tokens():
        wanted, silent = notify_prefs.push_rule(uid, "daily_nudge")
        if not wanted:
            continue
        try:
            with active_user_profile_context(_profile_for(uid)):
                nudge = get_daily_nudge(mongo_db, uid)
            text = str(nudge.get("text") or "").strip()
            if not text:
                continue
            data = {"kind": nudge.get("kind", "agenda")}
            if nudge.get("qid"):
                data["qid"] = nudge["qid"]
            for token in push_tokens_store.tokens_for_user(uid):
                ok, status = apns.send(token, "ساندي", text, data=data, silent=silent)
                if ok:
                    delivered += 1
                elif status == "gone":
                    push_tokens_store.unregister_token(token)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[nudge_sched] user %s failed: %s", uid, exc)
    logger.info("[nudge_sched] daily send delivered=%d", delivered)
    return delivered


def start_nudge_scheduler(mongo_db) -> bool:
    """Start the daily push job; no-op unless APNs is configured."""
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
        _scheduler = BackgroundScheduler(timezone=USER_TZ)
        _scheduler.add_job(
            run_daily_send, "cron", hour=_SEND_HOUR, minute=0,
            args=[mongo_db], id="daily_nudge_send", replace_existing=True,
            misfire_grace_time=3600, coalesce=True,
        )
        _scheduler.start()
        _started = True
        logger.info("[nudge_sched] started — daily push at %02d:00 %s", _SEND_HOUR, USER_TZ)
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("[nudge_sched] failed to start: %s", exc)
        return False
