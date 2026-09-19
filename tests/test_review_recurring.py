"""A recurring reminder moves to its next time instead of vanishing."""
from datetime import datetime, timedelta, timezone

import mongomock

from app import db as appdb
from app.features import reminders_store as rs
from app.utils.time import USER_TZ
from app.utils.user_profiles import active_user_profile_context

_P = {"user_id": "u1", "chat_id": "u1", "relation": "user", "permissions": "all"}


def _db():
    d = mongomock.MongoClient().db
    appdb.configure(d)
    return d


def test_daily_reminder_rolls_forward_keeping_local_time():
    d = _db()
    try:
        three_days_ago = (datetime.now(USER_TZ) - timedelta(days=3)).replace(
            hour=8, minute=0, second=0, microsecond=0)
        with active_user_profile_context(_P):
            assert rs.add_reminder("دوا", (three_days_ago + timedelta(days=4)).isoformat(),
                                   recurrence="RRULE:FREQ=DAILY")["success"]
            d["sandy_reminders"].update_many({}, {"$set": {"remind_at": three_days_ago}})
            items = rs.load_reminders()
        assert len(items) == 1, "the recurring reminder disappeared"
        nxt = datetime.fromisoformat(items[0]["remind_at"])
        assert nxt > datetime.now(timezone.utc) - timedelta(minutes=15)
        assert (nxt.astimezone(USER_TZ).hour, nxt.minute) == (8, 0)
        assert nxt - datetime.now(timezone.utc) <= timedelta(days=1)
    finally:
        appdb.reset()


def test_ended_rule_is_retired():
    d = _db()
    try:
        past = datetime.now(timezone.utc) - timedelta(days=5)
        until = (past + timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ")
        with active_user_profile_context(_P):
            rs.add_reminder("x", (datetime.now(USER_TZ) + timedelta(hours=1)).isoformat(),
                            recurrence=f"RRULE:FREQ=DAILY;UNTIL={until}")
            d["sandy_reminders"].update_many({}, {"$set": {"remind_at": past}})
            assert rs.load_reminders() == []
        assert d["sandy_reminders"].find_one({})["send_state"] == "sent"
    finally:
        appdb.reset()
