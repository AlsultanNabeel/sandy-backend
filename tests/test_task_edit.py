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


# ── the Tasks screen: a change is previewed (the same question as by talk), then saved ──

import json  # noqa: E402
from types import SimpleNamespace as NS  # noqa: E402


@pytest.fixture
def c(on, monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    from app.features import usage_store
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)
    return create_app(mongo_db=brain_db).test_client()


@pytest.fixture
def model(monkeypatch):
    from app.brain import background
    asked = []

    def call(what, messages, **kw):
        asked.append(what)
        return NS(choices=[NS(message=NS(content=json.dumps(
            {"tool": "web_search", "args": {"query": "silver price"}}), tool_calls=None))])
    monkeypatch.setattr(background, "call", call)
    return asked


def _h(uid="userA", language="en"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}", "X-Lang": language}


@pytest.mark.parametrize("language, said", [("ar", "فوراً كل ما يتغيّر"), ("en", "right away whenever it changes")])
def test_the_screen_previews_how_often_and_how_it_tells_then_saves(c, on, model, language, said):
    body = {"every_minutes": 120, "delivery": {"mode": "instant"}}
    r = c.post(f"/api/scheduled-tasks/{on}/preview", json=body, headers=_h(language=language))
    assert r.status_code == 200 and said in r.get_json()["summary"] and model == []
    with active_user_profile_context(A):
        assert tasks.every_minutes(schedules.get(on)) == 60          # a preview saves nothing
    r = c.patch(f"/api/scheduled-tasks/{on}", json=body, headers=_h(language=language))
    assert r.status_code == 200
    shown = r.get_json()["task"]
    assert shown["every_minutes"] == 120 and shown["delivery"] == {"mode": "instant"}


@pytest.mark.parametrize("language, words", [("ar", "شوفي سعر الفضة"), ("en", "check the silver price")])
def test_new_words_from_the_screen_bring_their_check_shown_before_saving(c, on, model, language, words):
    r = c.post(f"/api/scheduled-tasks/{on}/preview", json={"instructions": words},
               headers=_h(language=language))
    out = r.get_json()
    assert r.status_code == 200 and words in out["summary"] and model == ["task_check"]
    assert out["check"] == {"tool": "web_search", "args": {"query": "silver price"}}
    r = c.patch(f"/api/scheduled-tasks/{on}", json={"instructions": words, "check": out["check"]},
                headers=_h(language=language))
    assert r.status_code == 200 and model == ["task_check"]        # what was shown is saved
    with active_user_profile_context(A):
        row = schedules.get(on)
        assert row["payload"]["instructions"] == words
        assert row["payload"]["probe"]["args"] == {"query": "silver price"}


def test_new_words_saved_without_a_check_get_one(c, on, model):
    r = c.patch(f"/api/scheduled-tasks/{on}", json={"instructions": "check silver"}, headers=_h())
    assert r.status_code == 200 and model == ["task_check"]


@pytest.mark.parametrize("body, code", [
    ({"delivery": {"mode": "daily"}}, "bad_delivery"),
    ({"every_minutes": 0}, "bad_every"),
    ({"instructions": "x", "check": {"tool": "list_delete", "args": {}}}, "bad_check"),
    ({"instructions": "   "}, "bad_instructions"),
    ({}, "nothing_to_change"),
])
@pytest.mark.parametrize("language", ["ar", "en"])
def test_a_change_that_cannot_be_read_is_refused_in_his_language(c, on, model, body, code, language):
    r = c.patch(f"/api/scheduled-tasks/{on}", json=body, headers=_h(language=language))
    assert r.status_code == 400 and r.get_json()["error"] == code
    assert r.get_json()["message"] == lang.PHRASES[f"task_{code}"][language]
    with active_user_profile_context(A):
        assert schedules.get(on)["payload"]["instructions"] == "check gold"


def test_a_check_the_model_could_not_find_is_said(c, on, monkeypatch):
    from app.brain import background
    monkeypatch.setattr(background, "call", lambda *a, **k: NS(choices=[NS(message=NS(
        content="not json", tool_calls=None))]))
    r = c.post(f"/api/scheduled-tasks/{on}/preview", json={"instructions": "check silver"}, headers=_h())
    assert r.status_code == 503 and r.get_json()["error"] == "check_failed"


def test_another_user_or_the_switch_off_is_not_found(c, on, monkeypatch, model):
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA", "userB"]}')
    for path, method in ((f"/api/scheduled-tasks/{on}", "PATCH"), (f"/api/scheduled-tasks/{on}/preview", "POST")):
        assert c.open(path, method=method, json={"every_minutes": 30}, headers=_h("userB")).status_code == 404
    monkeypatch.setenv("SANDY_FLAGS", "{}")
    assert c.patch(f"/api/scheduled-tasks/{on}", json={"every_minutes": 30}, headers=_h()).status_code == 404
