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
def test_a_running_fill_is_read_with_the_field_it_is_on(on, language, words):
    _job(on, browser_job.RUNNING, progress={"steps": 7, "field": "Customer name"})
    out = _status(language)
    assert out["ok"] and words in out["reply"] and "Customer name" in out["reply"]


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


def test_the_progress_lines_come_about_every_twenty_seconds_and_wait_only_twenty_before_going_on():
    assert browser_job.PROGRESS_S == 20 and browser_job.WAIT_S == 20


@pytest.mark.parametrize("language, words", [("ar", "ما وصلني جوابك خلال"), ("en", "didn't hear back from you")])
def test_with_none_open_his_last_fill_is_read_with_how_it_ended_and_why(on, language, words):
    # 12 Nov: «شو صار بالتعبئة؟» after it closed was answered «يبدو إنه ما تمّت», a guess.
    _job(on, browser_job.STOPPED, reason="expired")
    out = _status(language)
    assert words in out["reply"] and "httpbin.org" in out["reply"]


@pytest.mark.parametrize("language, words", [("ar", "انقطعت التعبئة"), ("en", "was cut off")])
def test_his_newest_fill_is_the_one_read(on, language, words):
    old = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _job(on, browser_job.DONE, created_at=old)
    _job(on, browser_job.FAILED, reason="restart")
    assert words in _status(language)["reply"]


@pytest.mark.parametrize("language, guess, real", [
    ("ar", "يبدو إنه ما تمّت التعبئة.", "ما وصلني جوابك خلال"),
    ("en", "It seems the form didn't go through.", "didn't hear back from you")])
def test_a_guess_of_how_a_closed_fill_ended_is_replaced_by_how_it_did(on, language, guess, real):
    _job(on, browser_job.STOPPED, reason="expired")
    state = _turn(ScriptedModel(text_reply(guess)), "شو صار بالتعبئة؟" if language == "ar" else "what happened?")
    assert guess not in state["final_response"] and real in state["final_response"]


JOB = "1446ccfffcfd43188e17eb208cc0a7d2"


def _begun(monkeypatch, language):
    def fill(args, ctx):
        from app.brain import tools_browser
        with lang.using(language):
            return tools_browser._outcome(ctx, {"id": JOB, "site": "httpbin.org", "status": browser_job.RUNNING})
    monkeypatch.setitem(tools.HANDLERS, "page_fill", fill)
    monkeypatch.setattr(browser_job, "detach", lambda job: None)


@pytest.mark.parametrize("language, claim, words", [
    ("ar", "عبيته يا قلبي، بس التعبئة على الموقع طوّلت. رح أكملها بالخلفية. 🤍", "بلّشت أعبّي"),
    ("en", "Done, I filled it for you! I'll finish the rest in the background.", "I've started filling")])
def test_a_fill_only_begun_is_said_begun_in_the_codes_words(on, monkeypatch, language, claim, words):
    # 12 Nov: «عبّيته يا قلبي» of a fill that had only just begun.
    _begun(monkeypatch, language)
    state = _turn(ScriptedModel(tools_reply(call("page_fill", url="https://httpbin.org/forms/post", goal="x")),
                                text_reply(claim)), "عبّيلي النموذج" if language == "ar" else "fill the form")
    assert words in state["final_response"] and claim not in state["final_response"]
    assert "عبيته" not in state["final_response"] and "Done" not in state["final_response"]


@pytest.mark.parametrize("language, claim, real", [
    ("ar", "عبّيت النموذج وخلصت.", "لسا شغّالة"), ("en", "I filled the form, it's finished.", "still working")])
def test_a_fill_said_done_while_its_tool_reads_it_running_is_replaced(on, language, claim, real):
    _job(on, browser_job.RUNNING, progress={"steps": 2, "field": "Telephone"})
    state = _turn(ScriptedModel(tools_reply(call("fill_status")), text_reply(claim)),
                  "وين صارت؟" if language == "ar" else "where is it?")
    assert claim not in state["final_response"] and real in state["final_response"]


@pytest.mark.parametrize("language", ["ar", "en"])
def test_a_fills_question_is_one_sentence_last_with_its_note_before_it(language):
    # 12 Nov: «…قلّي شو أحط، أو قلّي اتركه.؟ (اه/لأ)».
    from app.brain import confirm, fill_values
    with lang.using(language):
        note = fill_values.asked([{"field": "Telephone"}])
        q = confirm.question(lang.say("fill_summary", site="httpbin.org", fields="Customer name: Nabeel") + "\n" + note)
    first, last = q.split("\n")
    assert first == note and last.endswith("(اه/لأ)" if language == "ar" else "(yes/no)")
    assert ".؟" not in q and ".?" not in q and "Nabeel" in last
