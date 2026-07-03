"""Daily-nudge delivery scheduler (Phase 7).

Once a day, in the user's morning, generate each user's nudge and push it to
their registered devices. This is the ONLY thing that turns the in-app card into
a notification that arrives with the app closed — so it starts only when APNs is
configured (paid Apple account). Without keys it stays completely idle: no
thread, no cost, and the free in-app-card path is unaffected.

Runs in-process (no extra dyno). Under gunicorn each worker would start its own
scheduler, so the actual send is guarded by an atomic per-day lock in Mongo —
whichever worker claims ``send:<date>`` first does the fan-out; the rest skip.
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
    """Atomically claim today's send so only one worker fans out. True if we won."""
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
    """Generate + push today's nudge to every user with a device. Returns the
    number of notifications delivered. Safe to call directly (tests/manual)."""
    from app.api.daily_nudge_api import get_daily_nudge
    from app.features import push_tokens_store

    if not _claim_daily_lock(mongo_db):
        logger.info("[nudge_sched] another worker owns today's send; skipping")
        return 0

    delivered = 0
    for uid in push_tokens_store.user_ids_with_tokens():
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
                ok, status = apns.send(token, "ساندي", text, data=data)
                if ok:
                    delivered += 1
                elif status == "gone":
                    push_tokens_store.unregister_token(token)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[nudge_sched] user %s failed: %s", uid, exc)
    logger.info("[nudge_sched] daily send delivered=%d", delivered)
    return delivered


def start_nudge_scheduler(mongo_db) -> bool:
    """Start the once-a-day push job. No-op (returns False) unless APNs is
    configured, so paying is the only switch needed to turn delivery on."""
    global _started, _scheduler
    if _started:
        return True
    if not apns.is_configured():
        logger.info("[nudge_sched] APNs not configured — push delivery idle")
        return False

    if mongo_db is not None:
        try:  # auto-clean old daily locks
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
