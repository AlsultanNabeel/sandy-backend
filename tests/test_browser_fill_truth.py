"""«Sent ✅» is said only of a send the gate saw leave after his yes and the site answered well
(7 Nov: the agent stopped on empty actions and its own English sentence was told as «انبعت ✅»).
Any other end says plainly it was not sent and why, in his language, and what the model wrote to
itself never reaches him."""
from __future__ import annotations

import pytest
from test_browser_fill import _fill, _job, _last_job, _level, world  # noqa: F401
from brain_fakes import brain_db  # noqa: F401

from app.brain import lang
from app.features import browser_job

MODEL = "The form could not be completed because the user did not provide all required information."
NOT_SENT = {"ar": "ما انبعت", "en": "wasn't sent"}


@pytest.mark.parametrize("language", ["ar", "en"])
def test_an_agent_that_stops_on_empty_actions_is_told_as_not_sent(world, monkeypatch, language):  # noqa: F811
    _level("submit")

    async def agent(row, gate, client, tab, user_id, asked):
        return {"status": browser_job.DONE, "result": MODEL}
    monkeypatch.setattr(browser_job, "AGENT", agent)
    out = _fill(language)
    assert out["ok"] is False and NOT_SENT[language] in out["reply"]
    assert "✅" not in out["reply"] and MODEL not in out["reply"]
    job = _job(_last_job())
    assert job["status"] == browser_job.FAILED and job["reason"] == "unfinished" and not job.get("result")


def _yes(language):
    _level("submit")
    asked = _fill(language)
    return _fill(language, confirmed_job=asked["ids"][0])


@pytest.mark.parametrize("language", ["ar", "en"])
def test_sent_is_said_of_a_send_the_site_answered_well(world, language):  # noqa: F811
    done = _yes(language)
    assert done["ok"] and "✅" in done["reply"]


@pytest.mark.parametrize("language, words", [("ar", "الموقع رفضه"), ("en", "the site refused it")])
def test_a_site_that_refuses_the_send_is_not_told_as_sent(world, language, words):  # noqa: F811
    world.answered = 500
    done = _yes(language)
    assert done["ok"] is False and words in done["reply"] and "✅" not in done["reply"]
    assert _job(_last_job())["status"] == browser_job.FAILED


@pytest.mark.parametrize("language, words", [("ar", "ما وصلني رد"), ("en", "no answer from the site")])
def test_a_send_with_no_answer_is_not_told_as_sent(world, language, words):  # noqa: F811
    world.answered = None
    done = _yes(language)
    assert done["ok"] is False and words in done["reply"] and "✅" not in done["reply"]


@pytest.mark.parametrize("reason", ["unfinished", "broke", "gate", "steps", "cost", "slow", "step_slow", "unsent"])
@pytest.mark.parametrize("language, words", [("ar", ("ما انبعت", "ما بعت")), ("en", ("wasn't sent", "was sent", "sent nothing"))])
def test_every_other_end_says_it_was_not_sent(reason, language, words):
    with lang.using(language):
        said = browser_job.told({"status": browser_job.FAILED, "reason": reason, "site": "x.example"})
    assert any(w in said for w in words) and "✅" not in said


# ── Giving the page back returns the fill to where it was ──

def _take_and_give(job, times=2):
    import time as _t

    from brain_fakes import A

    from app.utils.user_profiles import active_user_profile_context
    for _ in range(times):
        with active_user_profile_context(A):
            assert browser_job.take_over(job)
        _t.sleep(0.8)                                         # the fill sees it is his
        with active_user_profile_context(A):
            assert browser_job.give_back(job)
        _t.sleep(0.8)


def _releases(world):  # noqa: F811
    return [p for p in world.pressed if p[0] == "mouseReleased"]


def test_a_question_waiting_for_his_yes_still_waits_after_he_takes_and_gives_back_twice(world, monkeypatch):  # noqa: F811
    _level("submit")
    runs = []
    agent = browser_job.AGENT

    async def counted(*a, **kw):
        runs.append(1)
        return await agent(*a, **kw)
    monkeypatch.setattr(browser_job, "AGENT", counted)
    asked = _fill("en")
    job = asked["ids"][0]
    _take_and_give(job)
    assert _job(job)["status"] == browser_job.HELD and len(runs) == 1
    done = _fill("en", confirmed_job=job)
    assert done["ok"] and "✅" in done["reply"] and len(_releases(world)) == 1 and len(runs) == 1
    assert world.released == ["st1"]


def test_a_yes_while_the_page_is_his_answers_the_question_still_open(world):  # noqa: F811
    from brain_fakes import A

    from app.utils.user_profiles import active_user_profile_context
    _level("submit")
    asked = _fill("en")
    job = asked["ids"][0]
    with active_user_profile_context(A):
        browser_job.take_over(job)
    done = _fill("en", confirmed_job=job)
    assert done["ok"] and "✅" in done["reply"] and len(_releases(world)) == 1


# ── The lines she writes while it works, and the one question ──

def _chat(db, thread):
    return [m["text"] for m in (db["conversations"].find_one({"_id": thread}) or {}).get("messages") or []]


def test_progress_stops_the_moment_the_question_arrives_and_the_question_comes_once(world, monkeypatch, brain_db):  # noqa: F811
    import time as _t

    from test_browser_fill import C9, _wait_for
    _level("submit")
    world.mode = "slow"
    monkeypatch.setattr(browser_job, "WAIT_S", 0.3)
    monkeypatch.setattr(browser_job, "PROGRESS_S", 0.4)
    _fill("en", thread=C9)
    _wait_for(lambda: any("Are you sure" in t for t in _chat(brain_db, C9)))
    at = len(_chat(brain_db, C9))
    _t.sleep(1.5)
    said = _chat(brain_db, C9)
    assert len(said) == at and sum("Are you sure" in t for t in said) == 1


@pytest.mark.parametrize("language, seen, unseen", [
    ("ar", "هلّق عند «Telephone»", "خطوات"), ("en", "now at «Telephone»", "steps")])
def test_where_a_fill_is_said_without_a_count(language, seen, unseen):
    with lang.using(language):
        said = browser_job.state_line({"status": browser_job.RUNNING, "site": "x.example",
                                       "progress": {"steps": 1, "field": "Telephone"}})
    assert seen in said and unseen not in said


def test_a_fill_that_ended_takes_its_question_with_it(world, monkeypatch, brain_db):  # noqa: F811
    from test_browser_fill import C9, _wait_for

    from app.brain import pending
    _level("submit")
    world.mode = "slow"
    monkeypatch.setattr(browser_job, "WAIT_S", 0.3)
    monkeypatch.setattr(browser_job, "HOLD_S", 0.5)
    _fill("en", thread=C9)
    _wait_for(lambda: any("didn't hear back" in t for t in _chat(brain_db, C9)))
    assert pending.load(C9, "userA", brain_db) is None


@pytest.mark.parametrize("message", ["مطولة", "taking long?"])
def test_an_unrelated_message_never_asks_the_fills_question_again_nor_lets_it_go(brain_db, monkeypatch, message):  # noqa: F811
    from brain_fakes import A, ScriptedModel, text_reply

    from app.brain import confirm, loop
    from app.utils.user_profiles import active_user_profile_context
    with lang.using("en"):
        held = confirm.with_step(None, "page_fill", {"url": "https://x.example"}, "send the form", ids=["j1"])
        question = confirm.ask(held)
    state = held
    for _ in range(2):
        with active_user_profile_context(A):
            out = loop.run_turn(message, user_id="userA", chat_id="userA", source="web", pending_state=state,
                                complete=ScriptedModel(text_reply("ok")))
        state = out["pending_state"]
        assert question not in out["final_response"] and state and state["steps"][0]["ids"] == ["j1"]


# ── What is required and empty is asked before the question to send ──

@pytest.mark.parametrize("language, words", [("ar", "ناقصني"), ("en", "I still need")])
def test_required_empty_fields_are_asked_together_before_any_question_to_send(world, language, words):  # noqa: F811
    _level("submit")
    world.filled = [{"field": "Name", "value": "نبيل", "required": True},
                    {"field": "Telephone", "value": "", "required": True},
                    {"field": "E-mail", "value": "", "required": True},
                    {"field": "Notes", "value": "", "required": False}]
    out = _fill(language)
    assert not out.get("needs_confirmation") and words in out["reply"]
    assert "Telephone" in out["reply"] and "E-mail" in out["reply"] and "Notes" not in out["reply"]
    assert world.pressed == [] and world.released == ["st1"]


@pytest.mark.parametrize("language, empty", [("ar", "Notes: فاضي"), ("en", "Notes: empty")])
def test_optional_empty_fields_are_only_mentioned(world, language, empty):  # noqa: F811
    _level("submit")
    world.filled = [{"field": "Name", "value": "نبيل", "required": True},
                    {"field": "Notes", "value": "", "required": False}]
    out = _fill(language)
    assert out.get("needs_confirmation") and empty in out["summary"]


def test_she_never_asks_for_the_name_she_has():
    from app.brain import fill_values as FV
    field = {"label": "Customer name", "name": "custname", "type": "text", "choices": []}
    assert FV.vet_type(FV.his_values(["عبّي النموذج"], preferred_name="نبيل"), "نبيل", field) is None


# ── What the site answered is said in a sentence, never pasted ──

ECHO = '<html><body><pre>{ "args": {}, "headers": { "Accept": "text/html", "Host": "httpbin.org" } }</pre></body></html>'


def _judge(monkeypatch, answer):
    from types import SimpleNamespace as NS

    from app.brain import background
    seen = []

    def call(what, messages, **kw):
        seen.append((what, messages))
        if isinstance(answer, Exception):
            raise answer
        return NS(choices=[NS(message=NS(content=answer, tool_calls=None))])
    monkeypatch.setattr(background, "call", call)
    return seen


@pytest.mark.parametrize("language, words", [("ar", "والموقع استلمه"), ("en", "the site accepted it")])
def test_a_technical_page_is_said_in_a_sentence_never_pasted(world, monkeypatch, language, words):  # noqa: F811
    world.result = ECHO
    seen = _judge(monkeypatch, '{"accepted": true, "reason": ""}')
    done = _yes(language)
    assert done["ok"] and "✅" in done["reply"] and words in done["reply"]
    assert '"headers"' not in done["reply"] and "httpbin.org" not in done["reply"].replace("forms.example.com", "")
    assert seen[0][0] == "fill_result" and not _job(_last_job()).get("result")


@pytest.mark.parametrize("language", ["ar", "en"])
def test_a_page_that_refuses_is_said_with_its_reason_and_not_as_sent(world, monkeypatch, language):  # noqa: F811
    _judge(monkeypatch, '{"accepted": false, "reason": "رقم الهاتف غير صحيح"}')
    done = _yes(language)
    assert done["ok"] is False and "رقم الهاتف غير صحيح" in done["reply"] and "✅" not in done["reply"]
    assert _job(_last_job())["status"] == browser_job.FAILED


def test_a_reason_with_a_link_or_marks_never_reaches_him(world, monkeypatch):  # noqa: F811
    _judge(monkeypatch, '{"accepted": false, "reason": "go to [here](https://evil.example/x) now"}')
    done = _yes("en")
    assert done["ok"] is False and "evil.example" not in done["reply"] and "](" not in done["reply"]


@pytest.mark.parametrize("answer", [RuntimeError("no model"), "not json", '{"accepted": "maybe"}'])
def test_with_no_reading_of_the_page_it_says_only_that_it_was_sent(world, monkeypatch, answer):  # noqa: F811
    world.result = ECHO
    _judge(monkeypatch, answer)
    done = _yes("en")
    assert done["ok"] and "✅" in done["reply"] and '"headers"' not in done["reply"]
