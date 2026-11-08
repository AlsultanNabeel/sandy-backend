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
