"""What she says about a fill is its real state, read by a tool: `fill_status` reads his open
fills (running with its steps and the field it is on, waiting for his yes, his to finish, or
none); a reply that talks about a fill's state with no tool of the turn having read it has
that sentence replaced by the state as the code reads it (on 4 Nov she said «في مشكلة
بالتعبئة» of a fill that was working). A fill that goes on in the background writes in his
chat about every `PROGRESS_S` where it is, in words only, never spoken nor pushed. In both
languages."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.brain import honesty, lang, loop, tools
from app.brain.ctx import TurnCtx
from app.features import browser_job
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def on(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("SANDY_FLAGS", '{"browser": ["userA"]}')
    return brain_db


def _job(db, status, **more):
    now = datetime.now(timezone.utc)
    db[browser_job.COLLECTION].insert_one({"_id": f"job-{status}", "user_id": "userA", "site": "httpbin.org",
                                           "status": status, "closed_at": None, "created_at": now,
                                           "updated_at": now, **more})


def _status(language):
    with active_user_profile_context({**A, "chat_id": "userA"}), lang.using(language):
        return tools.execute("fill_status", {}, TurnCtx(user_id="userA"))


@pytest.mark.parametrize("language, words", [("ar", "لسا شغّالة"), ("en", "still working")])
def test_a_running_fill_is_read_with_its_steps_and_the_field_it_is_on(on, language, words):
    _job(on, browser_job.RUNNING, progress={"steps": 7, "field": "Customer name"})
    out = _status(language)
    with lang.using(language):
        seven = lang.number(7)
    assert out["ok"] and words in out["reply"] and seven in out["reply"] and "Customer name" in out["reply"]


@pytest.mark.parametrize("language, status, words", [
    ("ar", browser_job.HELD, "ناطرة موافقتك"), ("en", browser_job.HELD, "waiting for your yes"),
    ("ar", None, "ما في تعبئة مفتوحة"), ("en", None, "no fill open")])
def test_a_held_fill_or_none_is_read_as_it_is(on, language, status, words):
    if status:
        _job(on, status)
    assert words in _status(language)["reply"]


def _turn(model, message):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web", complete=model)


@pytest.mark.parametrize("language, invented, real", [
    ("ar", "آسفة على التأخير، بس يبدو إنه في مشكلة بالتعبئة.", "لسا شغّالة"),
    ("en", "Sorry, it looks like there is a problem with the form.", "still working")])
def test_talk_of_a_fills_state_no_tool_read_is_replaced_by_its_real_state(on, language, invented, real):
    _job(on, browser_job.RUNNING, progress={"steps": 4, "field": "Telephone"})
    state = _turn(ScriptedModel(text_reply(invented)), "مطولة" if language == "ar" else "taking long")
    assert invented not in state["final_response"] and real in state["final_response"]


def test_talk_of_a_fills_state_a_tool_read_stands(on):
    _job(on, browser_job.RUNNING, progress={"steps": 4, "field": "Telephone"})
    said = "The form is still being filled: four steps so far."
    state = _turn(ScriptedModel(tools_reply(call("fill_status")), text_reply(said)), "how is the form going?")
    assert said in state["final_response"]


@pytest.mark.parametrize("text", ["تمام، بعبّيلك النموذج هلّق.", "Sure, send me the form's link.",
                                  "The form has three fields."])
def test_words_about_a_form_that_claim_no_state_are_left_alone(text):
    assert not honesty.fill_state_talk(text)
