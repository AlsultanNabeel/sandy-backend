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


def test_a_daily_repeat_keeps_its_wall_clock_time_across_a_clock_change():
    """Cairo leaves summer time on 29 Oct 2026: 00:52 stays 00:52, so that day is 25 hours."""
    import pytest

    from app.utils.time import DEFAULT_ZONE
    if DEFAULT_ZONE != "Africa/Cairo":
        pytest.skip("written for the default zone")
    first = datetime(2026, 10, 28, 21, 52, tzinfo=timezone.utc)   # 00:52 at +03:00
    assert next_occurrence("FREQ=DAILY", first, first) == \
        datetime(2026, 10, 29, 22, 52, tzinfo=timezone.utc)        # 00:52 at +02:00
