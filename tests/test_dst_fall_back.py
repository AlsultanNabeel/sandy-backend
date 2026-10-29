"""The hour a clock goes back (Cairo, 29 Oct 2026 at midnight: 23:00–24:00 is lived twice).
Adding minutes to a wall-clock time inside that hour lands on its first pass, an hour early, so
a held yes expired the moment it was made and a task every N minutes was due again at once.
Time spans are counted on the universal clock."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.brain import pending
from app.services import schedule_runner

# 23:03 on Cairo's clock, the second time round (UTC+2): 21:03 UTC.
INSIDE = datetime(2026, 10, 29, 21, 3, 12, tzinfo=timezone.utc)


@pytest.fixture
def cairo(monkeypatch):
    monkeypatch.setattr("app.utils.time.current_zone", lambda: ZoneInfo("Africa/Cairo"))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return INSIDE.astimezone(tz) if tz else INSIDE.replace(tzinfo=None)
    monkeypatch.setattr(pending, "datetime", Clock)


def test_a_held_yes_made_in_the_repeated_hour_lives_its_ten_minutes(cairo):
    held = pending.create({"type": "brain_confirm"})
    assert pending.live(held)
    expires = datetime.fromisoformat(held["expires_at"])
    assert expires - INSIDE == timedelta(minutes=pending.TTL_MINUTES)


def test_a_task_every_hour_is_next_due_an_hour_later_in_the_repeated_hour(cairo):
    first = INSIDE - timedelta(minutes=2)
    nxt = schedule_runner.next_occurrence("FREQ=MINUTELY;INTERVAL=60", first, INSIDE)
    assert nxt == first + timedelta(hours=1)


def test_a_daily_reminder_still_keeps_its_wall_clock_hour(cairo):
    first = datetime(2026, 10, 28, 6, 0, tzinfo=timezone.utc)      # 9:00 Cairo summer time
    nxt = schedule_runner.next_occurrence("FREQ=DAILY", first, datetime(2026, 10, 30, 0, 0,
                                                                         tzinfo=timezone.utc))
    assert nxt.astimezone(ZoneInfo("Africa/Cairo")).hour == 9


def test_a_task_whose_series_began_in_the_repeated_hour_moves_an_hour_on(cairo):
    from app.blocks import schedules
    fire_at = INSIDE - timedelta(minutes=2)
    doc = {"_id": "t", "kind": "task", "recurrence": "FREQ=MINUTELY;INTERVAL=60",
           "fire_at": fire_at, "series_start": schedules.series_start(fire_at)}
    assert schedule_runner._next_time(doc, INSIDE) == fire_at + timedelta(hours=1)
