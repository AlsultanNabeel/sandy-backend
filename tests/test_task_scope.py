"""A task on his own data sees only the events of what it watches (the independent review of the
event log, 1 Nov 2026): a spending task was told «انضاف رمان لقائمة التسوق» and emailed it,
because a check with no list and no kind took every event as its own. Now a summary's scope is
its kind and its period, a search by words its kind and its words; a check with no clear scope
never reads the log and stays on comparing two reads; and the template only ever tells events
inside the scope."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app import notify
from app.blocks import entries, items, schedules, tasks
from app.brain import background, task_runner
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def world(brain_db, monkeypatch):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    sent, asked = [], []
    monkeypatch.setattr(notify, "CHANNELS", [lambda r: sent.append(r["body"])])

    def call(what, messages, **kw):
        asked.append((what, messages))
        return NS(choices=[NS(message=NS(content="MSG", tool_calls=None))])
    monkeypatch.setattr(background, "call", call)
    return NS(sent=sent, asked=asked, db=brain_db)


def _task(probe, language="ar"):
    spec = {"instructions": "تابعي", "notify_when": "شي جديد", "probe": probe,
            "tools": [probe["tool"]], "lang": language, "urgent": True}
    with active_user_profile_context(A):
        tid = tasks.add("مهمة", spec, every_minutes=1,
                        first_at=datetime.now(timezone.utc) + timedelta(minutes=1))
        return schedules.get(tid)


def _run(doc):
    with active_user_profile_context(A):
        return task_runner.run(doc, "userA")


SPENDING = {"tool": "summarize", "args": {"period": "month", "focus": "expense"}}


@pytest.mark.parametrize("language, fruit", [("ar", "رمان"), ("en", "pomegranate")])
def test_a_spending_task_is_not_told_of_a_shopping_item(world, language, fruit):
    doc = _task(SPENDING, language)
    _run(doc)                                       # where it starts
    with active_user_profile_context(A):
        items.add("shopping", fruit)
    _run(doc)
    assert world.sent == [] and world.asked == []
    assert world.db[notify.RESULTS].count_documents({}) == 0     # nothing kept, nothing emailed
    with active_user_profile_context(A):
        entries.add("expense", "قهوة", {"amount": 10})
    _run(doc)
    assert world.sent == ["MSG"]                    # its own kind is told


def test_a_summary_sees_only_its_period(world, monkeypatch):
    doc = _task({"tool": "summarize", "args": {"period": "today", "focus": "expense"}})
    _run(doc)
    with active_user_profile_context(A):
        entries.add("expense", "قهوة", {"amount": 10})
    real = task_runner.events.since
    # The same event, written yesterday: outside the period.
    monkeypatch.setattr(task_runner.events, "since", lambda seq: [
        {**e, "at": datetime.now(timezone.utc) - timedelta(days=2)} for e in real(seq)])
    _run(doc)
    assert world.sent == []


@pytest.mark.parametrize("language", ["ar", "en"])
def test_a_search_by_words_sees_its_kind_and_its_words(world, language):
    doc = _task({"tool": "recall", "args": {"kind": "expense", "query": "قهوة"}}, language)
    _run(doc)
    with active_user_profile_context(A):
        entries.add("expense", "غدا", {"amount": 30})          # its kind, not its words
        items.add("shopping", "قهوة")                         # its words, not its kind
    _run(doc)
    assert world.sent == []
    with active_user_profile_context(A):
        entries.add("expense", "قهوة الصبح", {"amount": 10})
    _run(doc)
    assert world.sent == ["MSG"]


def test_a_check_with_no_clear_scope_never_reads_the_log(world, monkeypatch):
    doc = _task({"tool": "recall", "args": {}})
    monkeypatch.setattr(task_runner.events, "since", lambda *a, **k: pytest.fail("read the log"))
    _run(doc)
    with active_user_profile_context(A):
        items.add("shopping", "رمان")
    _run(doc)
    with active_user_profile_context(A):
        assert "cursor" not in tasks.state(doc["id"])
    assert world.sent == ["انضاف «رمان» لـ«قائمة التسوق»"]    # from two reads, as before


def test_the_template_tells_only_events_inside_the_scope(world):
    doc = _task({"tool": "recall", "args": {"list": "shopping"}})
    _run(doc)
    with active_user_profile_context(A):
        items.add("tasks", "مش إلها")
        items.add("shopping", "رمان")
    _run(doc)
    assert world.sent == ["انضاف «رمان» لـ«قائمة التسوق»"]
