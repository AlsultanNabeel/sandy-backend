"""Scene timed-revert runner.

A scene action can say "for 30 minutes, then X" (``for_min`` / ``then``).
`apply_scene` stores those reverts in ``sandy_scene_timers``; this job is what
actually fires them. Before it existed nothing called `run_due_timers`, so a
"movie for two hours, then lights back on" scene never came back on.

Runs in-process once a minute. Under gunicorn each worker starts its own copy;
that is safe because every timer is claimed with an atomic find-and-delete
before it is sent, so a revert fires exactly once whichever worker gets it.
"""

from __future__ import annotations

import logging

from app.utils.user_profiles import active_user_profile_context

logger = logging.getLogger(__name__)

_started = False
_scheduler = None


def _profile_for(uid: str) -> dict:
    return {"chat_id": uid, "user_id": uid, "name": "", "relation": "user",
            "tone": "casual", "permissions": "all"}


def run_all_due(mongo_db) -> int:
    """Fire every owner's due reverts. Returns how many commands were sent.

    Safe to call directly (tests / manual). One owner's failure never stops
    the others.
    """
    from app.features import scene_store

    total = 0
    for uid in scene_store.users_with_due_timers(mongo_db):
        try:
            with active_user_profile_context(_profile_for(uid)):
                res = scene_store.run_due_timers()
            total += int(res.get("sent") or 0)
            if res.get("missed"):
                logger.info("[scene_timers] %s: missed %s", uid, res["missed"])
        except Exception as exc:  # noqa: BLE001
            logger.warning("[scene_timers] user %s failed: %s", uid, exc)
    return total


def start_scene_timer_runner(mongo_db) -> bool:
    """Start the once-a-minute job. No-op without a database."""
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
            id="scene_timer_revert", replace_existing=True,
            max_instances=1, coalesce=True, misfire_grace_time=120,
        )
        _scheduler.start()
        _started = True
        logger.info("[scene_timers] started — checking reverts every minute")
        return True
    except Exception as exc:  # noqa: BLE001
        logger.error("[scene_timers] failed to start: %s", exc)
        return False
