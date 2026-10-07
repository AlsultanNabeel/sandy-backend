"""Tells the user's phones their reminders changed, so a reminder made or moved anywhere
but the phone (the robot, the app's call, Sandy in chat, an undo) is scheduled there.

A silent background push (`apns.send_background`, `{"sync": "schedules"}`); the phone
reloads its reminders and schedules them. Changes within DEBOUNCE_S of each other go as one
push. Idle with no push keys, like every push.
"""

from __future__ import annotations

import logging
import threading
import time

from app.utils.thread_pool import submit_background

logger = logging.getLogger(__name__)

# The kinds the phone rings itself.
PHONE_KINDS = ("reminder",)
DEBOUNCE_S = 2.0
SYNC_DATA = {"sync": "schedules"}

_waiting: set = set()
_lock = threading.Lock()


def changed(kind: str = "reminder") -> None:
    """A schedule of the active user changed; their phones are told shortly."""
    from app.services import apns
    from app.utils.user_profiles import current_user_id

    uid = current_user_id()
    if not uid or kind not in PHONE_KINDS or not apns.is_configured():
        return
    with _lock:
        if uid in _waiting:
            return
        _waiting.add(uid)
    submit_background(_send, uid, _label="schedule_sync")


def _send(uid: str) -> None:
    from app.features import push_tokens_store
    from app.services import apns

    if DEBOUNCE_S:
        time.sleep(DEBOUNCE_S)
    with _lock:
        _waiting.discard(uid)
    for token in push_tokens_store.tokens_for_user(uid):
        ok, status = apns.send_background(token, SYNC_DATA)
        if status == "gone":
            push_tokens_store.unregister_token(token)
        elif not ok:
            logger.info("[schedule_sync] %s not told: %s", uid, status)
