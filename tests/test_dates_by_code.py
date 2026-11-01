"""Dates are the code's (the independent review of the event log, 1 Nov 2026): a task's
prompts say today's date and his clock and zone; «هالشهر», «الأسبوع الماضي» are computed by
the code in every tool that reads a period, never by the model; and a date more than a year
back, or far in the future, goes back to the model to ask him. In both languages."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app import notify
from app.blocks import entries, items, schedules, tasks
from app.brain import background, lang, task_runner, tools
from app.brain import when as W
from app.brain.ctx import TurnCtx
from app.utils.time import USER_TZ, zone_name
from app.utils.user_profiles import active_user_profile_context


def _tool(name, language="ar", **args):
    with active_user_profile_context(A), lang.using(language):
        return tools.execute(name, args, TurnCtx(user_id="userA"))


@pytest.mark.parametrize("language", ["ar", "en"])
def test_a_tasks_prompts_say_today_and_his_clock(brain_db, monkeypatch, language):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    monkeypatch.setattr(notify, "CHANNELS", [])
    asked = []
    monkeypatch.setattr(background, "call", lambda what, messages, **kw: asked.append((what, messages))
                        or NS(choices=[NS(message=NS(content="MSG", tool_calls=None))]))
    spec = {"instructions": "تابعي مصاريفي", "notify_when": "شي جديد", "lang": language, "urgent": True,
            "probe": {"tool": "summarize", "args": {"period": "month", "focus": "expense"}},
            "tools": ["summarize"]}
    with active_user_profile_context(A):
        doc = schedules.get(tasks.add("مصاريف", spec, every_minutes=1,
                                      first_at=datetime.now(timezone.utc) + timedelta(minutes=1)))
        task_runner.run(doc, "userA")
        entries.add("expense", "قهوة", {"amount": 10})
        task_runner.run(doc, "userA")
        today = datetime.now(USER_TZ).strftime("%Y-%m-%d")
        zone = zone_name()
    assert [w for w, _ in asked] == ["task", "task_review"]
    for _, messages in asked:
        assert today in messages[0]["content"] and zone in messages[0]["content"]


def test_last_week_and_last_month_are_the_codes():
    now = datetime(2026, 11, 4, 15, 0, tzinfo=timezone.utc)          # a Wednesday
    week_start, _ = W.period_range("week", now)
    start, end = (t.astimezone(USER_TZ) for t in W.period_range("last_week", now))
    assert end == week_start and (start.date(), start.hour) == ((end - timedelta(days=7)).date(), 0)
    assert start.weekday() == 5                                       # a Saturday
    start, end = W.period_range("last_month", now)
    assert (start.astimezone(USER_TZ).day, start.astimezone(USER_TZ).month) == (1, 10)
    assert (end.astimezone(USER_TZ).day, end.astimezone(USER_TZ).month) == (1, 11)


@pytest.mark.parametrize("language", ["ar", "en"])
def test_a_recall_takes_a_named_period(brain_db, language):  # noqa: F811
    now = datetime.now(timezone.utc)
    with active_user_profile_context(A):
        items.add("shopping", "رمان", done=True, done_at=now - timedelta(hours=1))
        items.add("shopping", "حليب", done=True, done_at=now - timedelta(days=70))
    out = _tool("recall", language, list="shopping", done=True, period="month")
    assert {r["text"] for r in out["rows"]} == {"رمان"}


@pytest.mark.parametrize("field, days", [("since", -400), ("until", 400), ("since", 800)])
def test_a_date_a_year_away_goes_back_to_ask(brain_db, field, days):  # noqa: F811
    out = _tool("recall", list="shopping", **{field: (datetime.now(timezone.utc) + timedelta(days=days)).date().isoformat()})
    assert out["ok"] is False and "ask" in out["error"]


def test_a_date_within_the_year_is_read(brain_db):  # noqa: F811
    out = _tool("recall", list="shopping", since=(datetime.now(timezone.utc) - timedelta(days=200)).date().isoformat())
    assert out["ok"] is True
