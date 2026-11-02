"""The emergency stop (`features/stop_all.py`, behind the `browser` switch): «وقّفي كل شي» by
talk, on the call, or from the app stops every task and every browser job at once, and one word
or one tap brings them back. Stopped, a task does not run and is no failure; a browser tool
refuses; reminders still ring. Another account is never stopped by it. In both languages."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace as NS

import pytest
from brain_fakes import A, B, brain_db  # noqa: F401

from app.blocks import schedules, tasks
from app.brain import lang, task_runner, tools, voice
from app.brain.ctx import TurnCtx
from app.features import stop_all
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def on(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA", "userB"], "browser": ["userA", "userB"]}')
    for uid in ("userA", "userB"):
        brain_db["sandy_users"].insert_one({"_id": uid})
    return brain_db


def _tool(name, user="userA", language="ar", **args):
    who = A if user == "userA" else B
    with active_user_profile_context(who), lang.using(language):
        return tools.execute(name, args, TurnCtx(user_id=user))


def test_the_stop_tools_are_offered_only_with_the_switch(on, monkeypatch):
    names = {s["function"]["name"] for s in tools.openai_tools("userA")}
    assert {"stop_everything", "resume_everything"} <= names
    assert {"stop_everything", "resume_everything"} <= {d["name"] for d in voice.declarations(user_id="userA")}
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": ["userA"]}')
    assert not {"stop_everything"} & {s["function"]["name"] for s in tools.openai_tools("userA")}


@pytest.mark.parametrize("language, stopped, back", [("ar", "وقّفت", "رجّعت"), ("en", "stopped", "back")])
def test_stop_and_resume_by_talk_say_so_in_his_language(on, language, stopped, back):
    out = _tool("stop_everything", language=language)
    assert out["ok"] and stopped in out["reply"].lower()
    assert stop_all.stopped("userA") and not stop_all.stopped("userB")
    out = _tool("resume_everything", language=language)
    assert out["ok"] and back in out["reply"].lower() and not stop_all.stopped("userA")


def test_without_the_switch_the_tools_refuse(on, monkeypatch):
    monkeypatch.setenv("SANDY_FLAGS", "{}")
    assert _tool("stop_everything")["ok"] is False and not stop_all.stopped("userA")


@pytest.fixture
def a_task(on, monkeypatch):
    asked = []
    monkeypatch.setattr("app.features.research.web_results", lambda q: [{"title": "P", "url": "u", "text": ""}])
    monkeypatch.setattr("app.brain.background.call", lambda *a, **kw: asked.append(a[0]) or NS(
        choices=[NS(message=NS(content="NOTHING", tool_calls=None))]))
    with active_user_profile_context(A):
        tid = tasks.add("projects", {"instructions": "x", "notify_when": "y", "lang": "en", "urgent": False,
                                     "probe": {"tool": "web_search", "args": {"query": "q"}},
                                     "tools": ["web_search"]},
                        every_minutes=60, first_at=datetime.now(timezone.utc) + timedelta(minutes=1))
        tasks.save_state(tid, {"last_seen": {"results": []}, "fingerprint": "old"})
        return schedules.get(tid)


def test_a_stopped_account_runs_no_task_and_counts_no_failure(a_task):
    stop_all.stop("userA")
    with active_user_profile_context(A):
        assert task_runner.run(a_task, "userA") is None
        state = tasks.state(a_task["id"])
    assert state.get("fingerprint") == "old" and not state.get("failures")


def test_after_resume_the_task_runs_again(a_task):
    stop_all.stop("userA")
    stop_all.resume("userA")
    with active_user_profile_context(A):
        task_runner.run(a_task, "userA")
        assert tasks.state(a_task["id"]).get("fingerprint") != "old"


def test_stopped_the_browser_refuses_in_his_language(on, monkeypatch):
    from app.features import web_page
    monkeypatch.setattr(web_page, "read", lambda *a, **kw: pytest.fail("read"))
    stop_all.stop("userA")
    out = _tool("page_read", language="en", url="https://notes.example/")
    assert out["ok"] is False and "stopped" in out["reply"].lower()


def test_stopping_closes_the_accounts_fills_and_nothing_else_is_kept_to_call(on, monkeypatch):
    from app.features import browser_job
    seen = []
    monkeypatch.setattr(browser_job, "stop_for", seen.append)
    stop_all.stop("userA")
    assert seen == ["userA"] and not hasattr(stop_all, "STOPPERS")


def test_the_app_stops_and_brings_back_with_one_call(on, monkeypatch):
    from app.api.auth_handlers import make_token
    from app.api.server import create_app
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    client = create_app(mongo_db=on).test_client()
    auth = {"Authorization": f"Bearer {make_token('user', user_id='userA')}"}
    assert client.get("/api/stop", headers=auth).get_json() == {"stopped": False}
    assert client.post("/api/stop", headers=auth).get_json() == {"stopped": True}
    assert stop_all.stopped("userA") and not stop_all.stopped("userB")
    assert client.delete("/api/stop", headers=auth).get_json() == {"stopped": False}
    other = {"Authorization": f"Bearer {make_token('user', user_id='userC')}"}
    assert client.post("/api/stop", headers=other).status_code == 404


@pytest.mark.parametrize("said", ["وقّفي كل شي", "ساندي وقفي كل شي!", "وقفي كلشي", "Stop everything", "sandy, stop everything."])
def test_the_stop_in_a_chat_message_stops_everything_whatever_the_model_does(on, said):
    """The emergency stop by text never waits on the model choosing the tool."""
    from brain_fakes import ScriptedModel, text_reply

    from app.brain import loop
    model = ScriptedModel(text_reply("حاضر"))
    with active_user_profile_context(A):
        out = loop.run_turn(said, user_id="userA", chat_id="userA", source="web", complete=model)
    assert stop_all.stopped("userA") and not stop_all.stopped("userB") and model.seen == []
    assert ("وقّفت" if lang.of(said) == "ar" else "stopped") in out["final_response"].lower()


@pytest.mark.parametrize("said", ["وقّفي كل شي بالمطبخ", "how do I stop everything from syncing?", "شو بصير لو وقفت كل شي"])
def test_a_message_that_only_mentions_stopping_goes_to_the_model(on, said):
    from brain_fakes import ScriptedModel, text_reply

    from app.brain import loop
    with active_user_profile_context(A):
        loop.run_turn(said, user_id="userA", chat_id="userA", source="web", complete=ScriptedModel(text_reply("ok")))
    assert not stop_all.stopped("userA")
