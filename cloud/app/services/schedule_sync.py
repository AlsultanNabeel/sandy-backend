"""Tells the user's phones their reminders or tasks changed, so a reminder made or moved
anywhere but the phone (the robot, the app's call, Sandy in chat, an undo) is scheduled there,
and a task changed anywhere, or a result it found, shows at once on the Tasks screen.

A silent background push (`apns.send_background`, `{"sync": "schedules"}` or
`{"sync": "tasks"}`); the phone reloads what it names. Changes of one kind within DEBOUNCE_S
of each other go as one push. Idle with no push keys, like every push.
"""

from __future__ import annotations

import logging
import threading
import time

from app.utils.thread_pool import submit_background

logger = logging.getLogger(__name__)

# What the phone is told for each kind it shows: the reminders it rings, the Tasks screen.
SYNC_BY_KIND = {"reminder": "schedules", "task": "tasks"}
DEBOUNCE_S = 2.0

_waiting: set = set()
_lock = threading.Lock()


def changed(kind: str = "reminder") -> None:
    """A schedule of the active user changed (or, for a task, a result it found); their phones
    are told shortly."""
    from app.services import apns
    from app.utils.user_profiles import current_user_id

    uid, what = current_user_id(), SYNC_BY_KIND.get(kind)
    if not uid or not what or not apns.is_configured():
        return
    with _lock:
        if (uid, what) in _waiting:
            return
        _waiting.add((uid, what))
    submit_background(_send, uid, what, _label="schedule_sync")


def _send(uid: str, what: str) -> None:
    from app.features import push_tokens_store
    from app.services import apns

    if DEBOUNCE_S:
        time.sleep(DEBOUNCE_S)
    with _lock:
        _waiting.discard((uid, what))
    for token in push_tokens_store.tokens_for_user(uid):
        ok, status = apns.send_background(token, {"sync": what})
        if status == "gone":
            push_tokens_store.unregister_token(token)
        elif not ok:
            logger.info("[schedule_sync] %s not told: %s", uid, status)
