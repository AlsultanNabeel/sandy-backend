"""Habit commitment days and streak: a day counts when every habit due that day was kept."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import entries, habits, items
from app.utils.time import USER_TZ
from app.utils.user_profiles import active_user_profile_context

NOW = datetime(2026, 10, 2, 20, 0, tzinfo=USER_TZ)  # a Friday


def _day(back: int) -> str:
    return (NOW - timedelta(days=back)).date().isoformat()


@pytest.fixture()
def tenant(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        yield


def _habit(text, days=None, added_back=10):
    return items.add("habits", text, {"days": days} if days else None,
                     created_at=NOW - timedelta(days=added_back))


def _keep(habit_id, back):
    entries.add("habit", "x", {"habit_item_id": habit_id, "date": _day(back)})


def test_a_day_counts_only_when_every_due_habit_was_kept(tenant):
    read, pray = _habit("قراءة"), _habit("صلاة")
    for back in (1, 2, 3):
        _keep(read, back)
        _keep(pray, back)
    _keep(read, 4)                      # only one of two: not a committed day
    p = habits.progress(NOW)
    assert p["base_committed"] == 3 and p["base_streak"] == 3
    assert p["committed_days"] == 3 and p["streak"] == 3   # today still open, not a break
    _keep(read, 0)
    _keep(pray, 0)
    assert habits.progress(NOW)["streak"] == 4


def test_a_day_with_nothing_due_neither_counts_nor_breaks(tenant):
    friday = habits.weekday(NOW.date())
    gym = _habit("جيم", days=[friday], added_back=20)   # only Fridays
    _keep(gym, 7)
    _keep(gym, 14)
    p = habits.progress(NOW)
    # The six days between the Fridays have nothing due: the two Fridays are a run of two.
    assert p["base_committed"] == 2 and p["base_streak"] == 2


def test_a_missed_due_day_breaks_the_streak(tenant):
    read = _habit("قراءة")
    _keep(read, 1)
    _keep(read, 3)                      # day 2 missed
    p = habits.progress(NOW)
    assert p["base_committed"] == 2 and p["base_streak"] == 1


def test_a_habit_counts_only_from_the_day_it_was_added(tenant):
    read = _habit("قراءة", added_back=10)
    _habit("رياضة", added_back=1)        # added yesterday
    for back in (2, 3):
        _keep(read, back)
    assert habits.progress(NOW)["base_committed"] == 2   # before yesterday only reading was due


def test_the_app_and_sandy_read_the_same_numbers(tenant, monkeypatch):
    from app.brain import context
    read = _habit("قراءة")
    _keep(read, 1)
    _keep(read, 2)
    monkeypatch.setattr(habits, "progress", lambda now=None: {"committed_days": 2, "streak": 2,
                                                              "base_committed": 2, "base_streak": 2})
    assert "2 يوم التزم" in context.state_block() and "السلسلة هلأ 2" in context.state_block()
