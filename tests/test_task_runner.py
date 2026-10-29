"""A task's run (`brain/task_runner.py`): the code checks first, the model only when something
changed, one review before a result goes out, three failures in a row stop it, and nothing is
ever said aloud. In both languages, with the same code for any field of work."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app import notify
from app.blocks import schedules, tasks
from app.brain import background, task_runner
from app.utils.user_profiles import active_user_profile_context

OWNER = "userA"


def _spec(language="en", tool="web_search", args=None, allowed=("web_search",)):
    return {"instructions": "check Mostaql for new projects" if language == "en" else
            "شوفي مشاريع جديدة على مستقل", "notify_when": "a new project",
            "probe": {"tool": tool, "args": args or {"query": "mostaql projects"}},
            "tools": list(allowed), "lang": language, "urgent": False}


@pytest.fixture
def world(brain_db, monkeypatch):  # noqa: F811
    """The switch on for the owner, a web that answers from `pages`, a model that answers
    from `answers`, and every delivery and model call kept."""
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    pages, answers, asked, sent = [[{"title": "P1", "url": "u1", "text": ""}]], [], [], []
    monkeypatch.setattr("app.features.research.web_results", lambda q: pages[0])

    def call(what, messages, **kw):
        asked.append(what)
        text = answers.pop(0) if answers else "NOTHING"
        return NS(choices=[NS(message=NS(content=text, tool_calls=None))])
    monkeypatch.setattr(background, "call", call)
    monkeypatch.setattr(notify, "CHANNELS", [lambda r: sent.append(r["body"])])
    return NS(pages=pages, answers=answers, asked=asked, sent=sent)


def _task(spec):
    with active_user_profile_context(A):
        tid = tasks.add("projects", spec, every_minutes=60,
                        first_at=datetime.now(timezone.utc) + timedelta(minutes=1))
        return schedules.get(tid)


def _run(doc):
    with active_user_profile_context(A):
        return task_runner.run(doc, OWNER)


@pytest.mark.parametrize("language", ["en", "ar"])
def test_twenty_runs_with_nothing_new_call_no_model_and_send_nothing(world, language):
    doc = _task(_spec(language))
    world.answers.append("NOTHING")
    _run(doc)                       # the first run sees the page for the first time
    world.asked.clear()
    for _ in range(20):
        _run(doc)
    assert world.asked == [] and world.sent == []


@pytest.mark.parametrize("language, said", [("en", "One new project: P2"),
                                            ("ar", "في مشروع جديد: P2")])
def test_the_first_change_is_one_message_after_one_review(world, language, said):
    doc = _task(_spec(language))
    world.answers.append("NOTHING")
    _run(doc)
    world.pages[0] = [{"title": "P1", "url": "u1", "text": ""}, {"title": "P2", "url": "u2", "text": ""}]
    world.asked.clear()
    world.answers += [said, said]
    _run(doc)
    _run(doc)                       # and the same page again: nothing more
    assert world.asked == ["task", "task_review"] and world.sent == [said]


def test_a_review_that_answers_nothing_sends_nothing(world):
    doc = _task(_spec())
    world.answers += ["Something", "NOTHING"]
    _run(doc)
    assert world.asked == ["task", "task_review"] and world.sent == []


@pytest.mark.parametrize("language, word", [("en", "stopped"), ("ar", "وقّفت")])
def test_three_failures_in_a_row_stop_it_and_say_so(world, monkeypatch, language, word):
    doc = _task(_spec(language))
    monkeypatch.setattr("app.features.research.web_results",
                        lambda q: (_ for _ in ()).throw(RuntimeError("down")))
    for _ in range(3):
        _run(doc)
    with active_user_profile_context(A):
        assert schedules.get(doc["id"])["status"] == "paused"
    assert len(world.sent) == 1 and word in world.sent[0] and world.asked == []


def test_an_account_without_the_switch_runs_nothing(world, monkeypatch):
    monkeypatch.setenv("SANDY_FLAGS", "{}")
    doc = _task(_spec())
    assert _run(doc) is None and world.asked == [] and world.sent == []


def test_a_check_may_only_read(world):
    doc = _task(_spec(tool="list_delete", args={"everything": True}))
    _run(doc)
    with active_user_profile_context(A):
        assert tasks.state(doc["id"])["failures"] == 1


def test_the_model_may_not_use_a_tool_the_task_was_not_given(world, monkeypatch):
    doc = _task(_spec())
    ran = []
    monkeypatch.setattr("app.brain.tools.execute", lambda name, args, ctx: ran.append(name) or {"ok": True})
    calls = iter([NS(choices=[NS(message=NS(content=None, tool_calls=[
        NS(id="c1", function=NS(name="list_delete", arguments='{"everything": true}'))]))]),
        NS(choices=[NS(message=NS(content="NOTHING", tool_calls=None))])])
    monkeypatch.setattr(background, "call", lambda what, messages, **kw: next(calls))
    _run(doc)
    assert "list_delete" not in ran


def test_a_task_due_is_run_and_never_rings_the_robot(world, monkeypatch):
    from app.services import schedule_runner
    monkeypatch.setattr(schedule_runner, "_ring_robot",
                        lambda *a: (_ for _ in ()).throw(AssertionError("she spoke")))
    doc = _task(_spec())
    world.answers += ["New: P1", "New: P1"]
    with active_user_profile_context(A):
        raw = {**doc, "_id": doc["id"]}
        assert schedule_runner._fire(raw, OWNER, datetime.now(timezone.utc)) == (True, "")
    assert world.sent == ["New: P1"]


# A task that is not urgent may go as a batch, at half the price, when batches are set up
# (off by default): the run submits its model step and a later run collects the answer.
def test_a_task_that_is_not_urgent_goes_as_a_batch_when_batches_are_on(world, monkeypatch):
    from app.brain import batch
    jobs, answers = [], [None, "New: P1"]
    monkeypatch.setenv("SANDY_BATCH_DEPLOYMENT", "sandy-batch")
    monkeypatch.setattr(batch, "submit", lambda what, messages, **kw: jobs.append(what) or "b1")
    monkeypatch.setattr(batch, "collect", lambda job: answers.pop(0))
    doc = _task(_spec())
    world.answers.append("New: P1")          # the review, made at once
    _run(doc)                                # submitted
    _run(doc)                                # still running
    assert jobs == ["task"] and world.sent == [] and world.asked == []
    _run(doc)                                # done: reviewed and sent
    assert world.asked == ["task_review"] and world.sent == ["New: P1"]


def test_batches_are_off_unless_set_up(world, monkeypatch):
    from app.brain import batch
    monkeypatch.delenv("SANDY_BATCH_DEPLOYMENT", raising=False)
    monkeypatch.setattr(batch, "submit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("batched")))
    world.answers += ["New: P1", "New: P1"]
    _run(_task(_spec()))
    assert world.sent == ["New: P1"]


def test_an_urgent_task_is_never_batched(world, monkeypatch):
    from app.brain import batch
    monkeypatch.setenv("SANDY_BATCH_DEPLOYMENT", "sandy-batch")
    monkeypatch.setattr(batch, "submit", lambda *a, **k: (_ for _ in ()).throw(AssertionError("batched")))
    world.answers += ["New: P1", "New: P1"]
    _run(_task({**_spec(), "urgent": True}))
    assert world.sent == ["New: P1"]


# The fingerprint is of what the data says, not of when it was read (review of session A): a
# device's «last seen», a period's end, the order results come in move by themselves.
def test_the_same_data_read_at_another_time_has_the_same_fingerprint():
    first = {"ok": True, "period": "month", "from": "2026-10-01", "to": "2026-10-29T20:00:00",
             "devices": [{"device": "AC", "state": "on", "last_seen": "قبل دقيقة"}],
             "results": [{"title": "P1", "url": "u1"}, {"title": "P2", "url": "u2"}]}
    later = {"ok": True, "period": "month", "from": "2026-10-01", "to": "2026-10-29T21:00:00",
             "devices": [{"device": "AC", "state": "on", "last_seen": "قبل ساعة"}],
             "results": [{"title": "P2", "url": "u2"}, {"title": "P1", "url": "u1"}]}
    assert task_runner.fingerprint(first) == task_runner.fingerprint(later)
    changed = {**later, "devices": [{"device": "AC", "state": "off", "last_seen": "هلّق"}]}
    assert task_runner.fingerprint(changed) != task_runner.fingerprint(first)


@pytest.mark.parametrize("language", ["en", "ar"])
def test_a_check_read_again_later_calls_no_model(world, monkeypatch, language):
    reads = iter([{"ok": True, "devices": [{"device": "AC", "state": "on", "last_seen": f"{n} min"}]}
                  for n in range(1, 30)])
    monkeypatch.setattr("app.brain.tools.execute", lambda name, args, ctx: next(reads))
    doc = _task(_spec(language, tool="device_state", args={}, allowed=("device_state",)))
    world.answers.append("NOTHING")
    _run(doc)
    world.asked.clear()
    for _ in range(20):
        _run(doc)
    assert world.asked == [] and world.sent == []


def test_every_run_hands_its_channels_what_they_held_even_with_nothing_new(world, monkeypatch):
    """What a channel held inside its hour (an email) goes on the task's next run after it."""
    flushed = []
    monkeypatch.setattr(notify, "FLUSHES", [flushed.append])
    doc = _task(_spec())
    _run(doc)
    _run(doc)                       # nothing new: no model, but the held still goes
    assert flushed == [doc["id"], doc["id"]]


def test_an_account_without_the_switch_flushes_nothing(world, monkeypatch):
    flushed = []
    monkeypatch.setattr(notify, "FLUSHES", [flushed.append])
    monkeypatch.setenv("SANDY_FLAGS", "{}")
    _run(_task(_spec()))
    assert flushed == []


# The minute runner finds a due task through its own due query (review of phase one): its kind
# was missing from `RUNNABLE`, so no task ever ran outside a direct call.
@pytest.mark.parametrize("language, said", [("en", "New: P1"), ("ar", "جديد: P1")])
def test_a_due_task_is_found_by_the_runners_own_scan_and_run(world, brain_db, language, said):  # noqa: F811
    from app.services import schedule_runner
    doc = _task(_spec(language))
    world.answers += [said, said]
    later = datetime.now(timezone.utc) + timedelta(minutes=2)
    assert schedule_runner.users_with_due(brain_db, later) == [OWNER]
    with active_user_profile_context(A):
        assert schedule_runner.run_due(OWNER, later)["fired"] == 1
        row = schedules.get(doc["id"])
    assert world.sent == [said] and row["status"] == "pending"
    assert row["fire_at"].replace(tzinfo=timezone.utc) > later


# A task only reads and tells (review of phase one): a reminder or a device is never among its
# tools, so its model cannot make one ring or switch anything without a yes. «Remind me two days
# before» is the task's own message through its channels.
def test_a_tasks_tools_only_read():
    assert set(tasks.ALLOWED) == set(tasks.READ_TOOLS)
    assert not {"schedule", "device_control", "scene_apply", "list_add", "remember"} & set(tasks.ALLOWED)


@pytest.mark.parametrize("language", ["en", "ar"])
def test_a_tasks_model_cannot_set_a_reminder_even_on_an_old_row(world, monkeypatch, language):
    doc = _task(_spec(language, tool="recall", args={"list": "tasks"}, allowed=("recall", "schedule")))
    ran = []
    real = task_runner.tools.execute
    monkeypatch.setattr("app.brain.tools.execute",
                        lambda name, args, ctx: ran.append(name) or real(name, args, ctx))
    calls = iter([NS(choices=[NS(message=NS(content=None, tool_calls=[
        NS(id="c1", function=NS(name="schedule", arguments='{"text": "deadline", "in_minutes": 5}'))]))]),
        NS(choices=[NS(message=NS(content="NOTHING", tool_calls=None))])])
    monkeypatch.setattr(background, "call", lambda what, messages, **kw: next(calls))
    _run(doc)
    with active_user_profile_context(A):
        assert ran == ["recall"] and schedules.list_schedules("reminder") == []


# The trace (review of phase one): every row a task's run leaves names the task, and its review
# is a call marked as one, so «one review per result sent» is read off the trace.
@pytest.mark.parametrize("language, said", [("en", "New: P1"), ("ar", "جديد: P1")])
def test_a_runs_trace_names_its_task_and_marks_the_review(brain_db, monkeypatch, language, said):  # noqa: F811
    from app.features import trace_store
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    monkeypatch.setattr("app.features.research.web_results", lambda q: [{"title": "P1", "url": "u1"}])
    monkeypatch.setattr(notify, "CHANNELS", [])

    def chat(**kw):
        trace_store.note_model_call("azure", "gpt-4o-mini", tokens_in=100, tokens_out=10)
        return NS(choices=[NS(message=NS(content=said, tool_calls=None))])
    monkeypatch.setattr("app.integrations.openai_client.chat_fn", lambda: chat)
    doc = _task(_spec(language))
    _run(doc)
    rows = list(brain_db[trace_store.COLLECTION].find({}))
    assert rows and all(r["task_id"] == doc["id"] for r in rows)
    assert [c.get("what") for r in rows for c in r["model_calls"]] == ["task", "task_review"]
    by_task = trace_store.costs()["by_task"]
    assert [(t["task_id"], t["runs"]) for t in by_task] == [(doc["id"], 1)]


# A task stopped by its failures starts from zero when he resumes it (review of phase one):
# one more failure after the resume used to stop it again at once.
@pytest.mark.parametrize("language, how", [("en", "tool"), ("ar", "tool"), ("en", "store")])
def test_a_resumed_task_starts_its_failures_from_zero(world, monkeypatch, language, how):
    from app.brain import tools_tasks
    from app.brain.ctx import TurnCtx
    doc = _task(_spec(language))
    monkeypatch.setattr("app.features.research.web_results",
                        lambda q: (_ for _ in ()).throw(RuntimeError("down")))
    for _ in range(3):
        _run(doc)
    with active_user_profile_context(A):
        assert schedules.get(doc["id"])["status"] == "paused"
        if how == "tool":
            assert tools_tasks.task_update({"id": doc["id"], "resume": True},
                                           TurnCtx(user_id=OWNER))["ok"]
        else:
            assert tasks.resume(doc["id"])
        assert tasks.state(doc["id"])["failures"] == 0
    _run(doc)
    with active_user_profile_context(A):
        assert schedules.get(doc["id"])["status"] == "pending"
        assert tasks.state(doc["id"])["failures"] == 1
