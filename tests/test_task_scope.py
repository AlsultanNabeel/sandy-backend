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


# ── on his yes the start keeps where the log is, in the same moment it reads (review, 1 Nov):
# it kept the read with no pointer, so its first run took itself for an old task and moved to
# the log quietly, and what he added in between was never told ──

@pytest.mark.parametrize("language, told", [("ar", "انضاف «رمان» لـ«قائمة التسوق»"),
                                            ("en", "«رمان» was added to «Shopping list»")])
def test_what_is_added_after_the_yes_is_told_by_the_next_run(world, language, told):
    from app.brain import lang, tools
    from app.brain.ctx import TurnCtx
    from app.blocks import events
    args = {"title": "التسوق", "instructions": "تابعي قائمة التسوق", "every_minutes": 60,
            "check_tool": "recall", "check_args": {"list": "shopping"}}
    with active_user_profile_context(A), lang.using(language):
        ctx = TurnCtx(user_id="userA")
        ctx.confirmed = True
        assert tools.execute("task_create", args, ctx)["ok"]
        [row] = tasks.running()
        assert tasks.state(row["id"])["cursor"] == events.last_seq()
        items.add("shopping", "رمان")
    _run(row)
    assert world.sent == [told]


def test_a_start_that_cannot_read_still_keeps_where_the_log_is(world, monkeypatch):
    doc = _task({"tool": "recall", "args": {"list": "shopping"}})
    monkeypatch.setattr(task_runner, "_probe", lambda spec, ctx: (_ for _ in ()).throw(RuntimeError("down")))
    with active_user_profile_context(A):
        assert task_runner.start(doc["id"], "userA") is None
    monkeypatch.undo()
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    monkeypatch.setattr(notify, "CHANNELS", [lambda r: world.sent.append(r["body"])])
    with active_user_profile_context(A):
        items.add("shopping", "رمان")
    _run(doc)
    assert world.sent == ["انضاف «رمان» لـ«قائمة التسوق»"]


def test_only_a_task_made_before_the_log_moves_to_it_quietly(world):
    old, new = _task({"tool": "recall", "args": {"list": "shopping"}}), \
        _task({"tool": "recall", "args": {"list": "shopping"}})
    with active_user_profile_context(A):
        world.db["sandy_schedules"].update_one(
            {"_id": old["id"]}, {"$set": {"created_at": task_runner.LOG_FROM - timedelta(days=1)}})
        for doc in (old, new):
            tasks.save_state(doc["id"], {"last_seen": {"rows": []}, "fingerprint": "x"})
        items.add("shopping", "رمان")
    _run(schedules_get(old["id"])), _run(schedules_get(new["id"]))
    assert world.sent == ["انضاف «رمان» لـ«قائمة التسوق»"]       # the new one only


def schedules_get(tid):
    with active_user_profile_context(A):
        return schedules.get(tid)
