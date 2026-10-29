"""A task (`blocks/tasks.py`): a `sandy_schedules` row of kind «task» that repeats, can be
paused, and remembers what it last saw (`sandy_task_state`), under its own user only."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, B, brain_db  # noqa: F401

from app.blocks import schedules, tasks
from app.utils.user_profiles import active_user_profile_context

SPEC = {"instructions": "check the price", "probe": {"tool": "web_search", "args": {"query": "x"}},
        "notify_when": "it changes", "tools": ["web_search"], "lang": "en", "urgent": False}


def _soon():
    return datetime.now(timezone.utc) + timedelta(minutes=5)


def test_a_task_repeats_every_n_minutes_and_lists_as_running(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        tid = tasks.add("the price", SPEC, every_minutes=60, first_at=_soon())
        row = schedules.get(tid)
        assert row["kind"] == "task" and row["recurrence"] == "FREQ=MINUTELY;INTERVAL=60"
        assert [t["id"] for t in tasks.running()] == [tid]


def test_paused_is_not_due_and_resumes(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        tid = tasks.add("the price", SPEC, every_minutes=60, first_at=_soon())
        assert tasks.pause(tid) and schedules.get(tid)["status"] == "paused"
        assert [t["status"] for t in tasks.running()] == ["paused"]
        assert tasks.resume(tid) and schedules.get(tid)["status"] == "pending"


def test_its_interval_changes(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        tid = tasks.add("the price", SPEC, every_minutes=60, first_at=_soon())
        assert tasks.set_every(tid, 120)
        assert schedules.get(tid)["recurrence"] == "FREQ=MINUTELY;INTERVAL=120"


def test_what_it_saw_is_kept_for_its_user_only(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        tid = tasks.add("the price", SPEC, every_minutes=60, first_at=_soon())
        tasks.save_state(tid, {"fingerprint": "abc", "failures": 0})
        assert tasks.state(tid)["fingerprint"] == "abc"
    with active_user_profile_context(B):
        assert tasks.state(tid) == {} and tasks.running() == []


def test_removed_takes_its_state_with_it(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        tid = tasks.add("the price", SPEC, every_minutes=60, first_at=_soon())
        tasks.save_state(tid, {"fingerprint": "abc"})
        assert tasks.remove(tid)
        assert schedules.get(tid) is None and tasks.state(tid) == {}


@pytest.mark.parametrize("minutes", [0, -5])
def test_an_interval_must_be_minutes_above_zero(brain_db, minutes):  # noqa: F811
    with active_user_profile_context(A), pytest.raises(ValueError):
        tasks.add("x", SPEC, every_minutes=minutes, first_at=_soon())


# A task is made only through its own tool, after a yes: never by a reminder's tool or the
# schedules route, which would skip the yes.
def test_the_reminder_tool_cannot_make_a_task(brain_db):  # noqa: F811
    from app.brain import tools
    from app.brain.ctx import TurnCtx
    spec = next(t for t in tools.openai_tools() if t["function"]["name"] == "schedule")["function"]
    assert "task" not in spec["parameters"]["properties"]["kind"]["enum"]
    with active_user_profile_context(A):
        out = tools.execute("schedule", {"kind": "task", "text": "x", "in_minutes": 5},
                            TurnCtx(user_id="userA"))
        assert not out["ok"] and tasks.running() == []

