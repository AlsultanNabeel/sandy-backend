"""«Let me watch» is the app's own button, made from the reply's structured `live` ({job}), never
a link the model writes: on 4 Nov the model wrote «[هون](sandy://browser/live?job=…).» and the
app read «…).» into the job's id (404). The tools' sentences carry no link, a link the model
writes anyway is taken out by the code, and the job rides with the reply (`/api/agent`, its
stream, the conversation's kept message, and what a fill says in the chat on its own)."""
from __future__ import annotations

import json

import mongomock
import pytest
from brain_fakes import A, ScriptedModel, brain_db, call, text_reply, tools_reply  # noqa: F401

from app.brain import lang, loop, tools, tools_browser
from app.brain.ctx import TurnCtx
from app.features import browser_job
from app.utils.user_profiles import active_user_profile_context

JOB = "1446ccfffcfd43188e17eb208cc0a7d2"


@pytest.mark.parametrize("language", ["ar", "en"])
def test_a_fill_that_goes_on_in_the_background_says_so_with_no_link_and_names_its_job(brain_db, monkeypatch, language):  # noqa: F811
    monkeypatch.setattr(browser_job, "detach", lambda job: None)
    ctx = TurnCtx(user_id="userA")
    with lang.using(language):
        out = tools_browser._outcome(ctx, {"id": JOB, "site": "httpbin.org", "status": browser_job.RUNNING})
    assert out["ok"] and "sandy://" not in out["reply"] and ctx.artifacts["live"] == {"job": JOB}


@pytest.mark.parametrize("language", ["ar", "en"])
def test_a_page_handed_to_him_is_told_with_no_link(language):
    with lang.using(language):
        said = browser_job.told({"id": JOB, "status": browser_job.HANDED, "site": "httpbin.org", "summary": "Name: x"})
    assert "sandy://" not in said


def _turn(model, message):
    with active_user_profile_context(A):
        return loop.run_turn(message, user_id="userA", chat_id="userA", source="web", complete=model)


@pytest.mark.parametrize("written", [
    "بكمّلها بالخلفية. تقدر تتفرّج من [هون](sandy://browser/live?job=1446ccfffcfd43188e17eb208cc0a7d2).",
    "It goes on in the background: sandy://browser/live?job=1446ccfffcfd43188e17eb208cc0a7d2"])
def test_a_link_the_model_writes_is_taken_out_and_the_job_rides_with_the_reply(brain_db, monkeypatch, written):  # noqa: F811
    def fill(args, ctx):
        ctx.artifacts["live"] = {"job": JOB}
        return {"ok": True, "reply": "background", "job": JOB}
    monkeypatch.setitem(tools.HANDLERS, "page_fill", fill)
    monkeypatch.setenv("SANDY_FLAGS", '{"browser": ["userA"]}')
    state = _turn(ScriptedModel(tools_reply(call("page_fill", url="https://httpbin.org/forms/post", goal="x")),
                                text_reply(written)), "عبّي النموذج")
    assert "sandy://browser/live" not in state["final_response"] and "](" not in state["final_response"]
    assert state["live"] == {"job": JOB}


@pytest.fixture()
def app(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    from app.features import usage_store
    monkeypatch.setattr(loop, "run_turn", lambda message, **kw: {"final_response": "ok", "live": {"job": JOB}})
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)
    db = mongomock.MongoClient().db
    return create_app(mongo_db=db).test_client(), db


def _h(uid="u1"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


def test_the_reply_and_its_stream_carry_the_job(app):
    client, _ = app
    assert client.post("/api/agent", json={"message": "عبّي"}, headers=_h()).get_json()["live"] == {"job": JOB}
    events = [json.loads(line[6:]) for line in client.post("/api/agent/stream", json={"message": "عبّي"}, headers=_h())
              .get_data(as_text=True).splitlines() if line.startswith("data: ")]
    assert events[-1]["done"] and events[-1]["live"] == {"job": JOB}


def test_the_kept_message_keeps_its_job_and_nothing_else(app):
    client, _ = app
    cid = "conv-12345678"
    for live in ({"job": JOB}, {"job": "x/../y"}, "sandy://browser/live?job=1"):
        client.post(f"/api/conversations/{cid}/messages", json={"role": "sandy", "text": "t", "live": live}, headers=_h())
    kept = client.get(f"/api/conversations/{cid}", headers=_h()).get_json()["messages"]
    assert kept[0]["live"] == {"job": JOB} and "live" not in kept[1] and "live" not in kept[2]


def test_what_a_fill_says_on_its_own_carries_its_job(app):
    from app.api.conversations_api import say_in
    _, db = app
    assert say_in(db, "u1", "conv-12345678", "انبعت ✅", live={"job": JOB})
    message = db["conversations"].find_one({"_id": "conv-12345678"})["messages"][-1]
    assert message["live"] == {"job": JOB}
