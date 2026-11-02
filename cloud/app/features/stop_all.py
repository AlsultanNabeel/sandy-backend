"""The emergency stop: «وقّفي كل شي», by talk, on the call, or from the app (behind the `browser`
switch).

Stopped (`sandy_users.stopped_at`), an account's tasks do not run and count no failure
(`task_runner.run`), the browser's tools refuse (`tools_browser`), and every browser job still
running stops at its next step and closes its session (`browser_job.stop_for`, then any other
in `STOPPERS`). Reminders still ring: they are his, not work Sandy does on her own. One word or one
tap (`resume`) brings it all back. A reset forgets it (`account_delete.USER_ROW_FORGOTTEN`).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, List

from pymongo.errors import PyMongoError

from app.db import get_db

logger = logging.getLogger(__name__)

_USERS = "sandy_users"
FIELD = "stopped_at"
# Called with the account's id once it is stopped, after the browser's fills: what else still
# runs for it stops.
STOPPERS: List[Callable[[str], None]] = []


def stopped(user_id: str) -> bool:
    """Whether the account is stopped; a read that fails is not a stop (logged)."""
    db = get_db()
    if db is None or not user_id:
        return False
    try:
        row = db[_USERS].find_one({"_id": str(user_id)}, {FIELD: 1}) or {}
    except PyMongoError:
        logger.warning("[stop] could not read whether %s is stopped", user_id, exc_info=True)
        return False
    return bool(row.get(FIELD))


def _set(user_id: str, value) -> bool:
    db = get_db()
    if db is None or not user_id:
        return False
    change = {"$set": {FIELD: value}} if value else {"$unset": {FIELD: ""}}
    try:
        return db[_USERS].update_one({"_id": str(user_id)}, change).matched_count == 1
    except PyMongoError:
        logger.warning("[stop] could not change %s", user_id, exc_info=True)
        return False


def stop(user_id: str) -> bool:
    """Everything of this account's own work stops now; True once it is kept."""
    from app.features import browser_job
    kept = _set(user_id, datetime.now(timezone.utc))
    for stopper in (browser_job.stop_for, *STOPPERS):
        try:
            stopper(str(user_id))
        except (RuntimeError, OSError, ValueError, PyMongoError):  # the rest still stop
            logger.exception("[stop] a stopper failed for %s", user_id)
    return kept


def resume(user_id: str) -> bool:
    """It all goes on again; True once it is kept."""
    return _set(user_id, None)
