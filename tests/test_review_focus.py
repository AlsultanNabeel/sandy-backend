"""A pomodoro advances by itself: nothing runs it on a timer."""
from datetime import datetime, timedelta, timezone

import mongomock

from app import db as appdb
from app.features import focus_store
from app.utils.user_profiles import active_user_profile_context

_P = {"user_id": "u1", "chat_id": "u1", "relation": "user", "permissions": "all"}


def test_an_elapsed_session_finishes_and_a_new_one_can_start():
    d = mongomock.MongoClient().db
    appdb.configure(d)
    try:
        with active_user_profile_context(_P):
            assert focus_store.start_focus(focus_min=25, break_min=5, cycles=2)["ok"]
            # Pretend the whole session happened an hour ago.
            past = datetime.now(timezone.utc) - timedelta(hours=2)
            d["sandy_focus"].update_many({}, {"$set": {"started_at": past,
                                                      "phase_ends_at": past + timedelta(minutes=25)}})
            assert focus_store.focus_status() == {"active": False}
            assert focus_store.start_focus(focus_min=25)["ok"]
    finally:
        appdb.reset()
