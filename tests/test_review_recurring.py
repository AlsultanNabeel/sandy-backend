"""A recurring schedule moves to its next time, in local time, and retires when its rule ends."""
from datetime import datetime, timedelta, timezone

from app.services.schedule_runner import next_occurrence
from app.utils.time import USER_TZ


def test_a_daily_rule_rolls_forward_keeping_local_time():
    now = datetime.now(timezone.utc)
    three_days_ago = (datetime.now(USER_TZ) - timedelta(days=3)).replace(
        hour=8, minute=0, second=0, microsecond=0)
    nxt = next_occurrence("RRULE:FREQ=DAILY", three_days_ago, now)
    assert nxt > now and nxt - now <= timedelta(days=1)
    assert (nxt.astimezone(USER_TZ).hour, nxt.astimezone(USER_TZ).minute) == (8, 0)
    assert nxt.tzinfo is not None


def test_an_ended_rule_has_no_next_time():
    past = datetime.now(timezone.utc) - timedelta(days=5)
    until = (past + timedelta(days=1)).strftime("%Y%m%dT%H%M%SZ")
    assert next_occurrence(f"FREQ=DAILY;UNTIL={until}", past, datetime.now(timezone.utc)) is None
