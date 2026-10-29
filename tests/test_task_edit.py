"""A task is changed the same way from everywhere (the owner's, 29 Oct): its words (what it
does, its check), how often, how it tells, pause, resume and remove, by talk in the chat and
in a call (the app's or the robot's) and from the app's Tasks screen; a change of what it
does is shown and waits for a yes, from the screen as by talk. In both languages, behind
the `tasks` switch."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import schedules, tasks
from app.brain import lang, tools, voice
from app.brain.ctx import TurnCtx
from app.utils.user_profiles import active_user_profile_context

GOLD = {"instructions": "check gold", "notify_when": "it moves", "lang": "en", "urgent": False,
        "probe": {"tool": "web_search", "args": {"query": "gold price"}}, "tools": ["web_search"]}


@pytest.fixture
def on(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    with active_user_profile_context(A):
        tid = tasks.add("Gold", GOLD, every_minutes=60,
                        first_at=datetime.now(timezone.utc) + timedelta(hours=1))
        tasks.save_state(tid, {"fingerprint": "old", "last_probe": "gold 100"})
    return tid


def _run(name, language, confirmed=False, **args):
    with active_user_profile_context(A), lang.using(language):
        ctx = TurnCtx(user_id="userA")
        ctx.confirmed = confirmed
        return tools.execute(name, args, ctx)


@pytest.mark.parametrize("language, words", [("ar", "شوفي سعر الفضة"), ("en", "check the silver price")])
def test_its_words_are_changed_by_talk_after_a_yes(on, language, words):
    args = {"id": on, "instructions": words, "check_tool": "web_search",
            "check_args": {"query": "silver price"}}
    asked = _run("task_update", language, **args)
    assert asked.get("needs_confirmation") and words in asked["summary"]
    with active_user_profile_context(A):
        assert schedules.get(on)["payload"]["instructions"] == "check gold"
    assert _run("task_update", language, confirmed=True, **args)["ok"]
    with active_user_profile_context(A):
        row = schedules.get(on)
        assert row["payload"]["instructions"] == words
        assert row["payload"]["probe"] == {"tool": "web_search", "args": {"query": "silver price"}}
        assert "fingerprint" not in tasks.state(on) or not tasks.state(on)["fingerprint"]


def test_a_new_check_may_only_read(on):
    out = _run("task_update", "en", confirmed=True, id=on, instructions="x", check_tool="list_delete")
    assert not out["ok"]
    with active_user_profile_context(A):
        assert schedules.get(on)["payload"]["instructions"] == "check gold"


def test_words_that_ask_to_act_make_the_yes_say_a_task_only_reads(on):
    asked = _run("task_update", "en", id=on, instructions="pay the gold dealer every week")
    assert asked.get("needs_confirmation") and "never pays" in asked["summary"]


def test_how_often_and_how_it_tells_still_change_at_once(on):
    assert _run("task_update", "en", id=on, every_minutes=120, notify_how="instant")["ok"]
    with active_user_profile_context(A):
        row = schedules.get(on)
        assert tasks.every_minutes(row) == 120 and tasks.how(row) == {"mode": "instant"}


@pytest.mark.parametrize("robot", [False, True])
def test_a_call_changes_its_words_too_the_robots_as_the_apps(on, robot):
    names = {d["name"]: d for d in voice.declarations(end_call=robot, user_id="userA")}
    update = names["task_update"]["parameters"]["properties"]
    assert {"instructions", "check_tool", "check_args", "notify_how"} <= set(update)
    assert update["check_args"]["properties"], "Gemini refuses an object with no fields"
    assert ("end_call" in names) == robot
    with active_user_profile_context(A), lang.using("ar"):
        held = voice.dispatch("task_update", {"id": on, "instructions": "شوفي سعر الفضة",
                                              "check_tool": "web_search",
                                              "check_args": {"query": "سعر الفضة"}}, "userA")
        assert held["handled"] and schedules.get(on)["payload"]["instructions"] == "check gold"
        voice.dispatch("confirm", {"answer": "اه"}, "userA")
        assert schedules.get(on)["payload"]["instructions"] == "شوفي سعر الفضة"


def test_the_robots_call_has_the_task_tools_only_with_the_switch(on, monkeypatch):
    names = {d["name"] for d in voice.declarations(end_call=True, user_id="userA")}
    assert {"task_create", "task_list", "task_update", "task_cancel", "end_call"} <= names
    monkeypatch.setenv("SANDY_FLAGS", "{}")
    assert "task_update" not in {d["name"] for d in voice.declarations(end_call=True, user_id="userA")}
