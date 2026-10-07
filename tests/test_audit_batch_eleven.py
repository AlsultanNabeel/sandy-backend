"""Audit batch 11 (chat): «أعد المحاولة» sends the failed line again under its own id.

* A turn that finished on the server while its reply was lost on the way is answered
  from the ledger on the retry: the stored reply, and its tools are not run again
  (a reminder is not added twice), for as long as a retry can reasonably come (a day).
* The id is the send's within its user and its conversation: the same id in another
  conversation is its own turn.
* The user's line sent again under the same id is not added to the conversation twice.
"""
from __future__ import annotations

import json
import uuid

import mongomock
import pytest


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    from app.brain import loop
    from app.features import usage_store

    reminders = []

    def fake_run_turn(message, **kw):
        # Stands for a turn whose tool writes: each run adds one reminder.
        reminders.append((message, kw.get("conversation_id")))
        return {"final_response": f"ذكّرتك: {message}"}

    monkeypatch.setattr(loop, "run_turn", fake_run_turn)
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)

    db = mongomock.MongoClient().db
    app = create_app(mongo_db=db)
    return app.test_client(), db, reminders


def _h(uid):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


def _sse_done(resp):
    events = [json.loads(line[len("data: "):])
              for line in resp.get_data(as_text=True).splitlines()
              if line.startswith("data: ")]
    return events[-1]


def test_a_retry_after_the_reply_was_lost_gets_the_stored_reply_and_runs_no_tool(env):
    c, db, reminders = env
    cid, cmid = uuid.uuid4().hex, uuid.uuid4().hex
    body = {"message": "ذكريني بالدوا", "conversation_id": cid, "client_msg_id": cmid}

    first = _sse_done(c.post("/api/agent/stream", json=body, headers=_h("u1")))
    assert first["reply"] == "ذكّرتك: ذكريني بالدوا"
    # The phone never got it (the network went); the user taps «أعد المحاولة».
    again = _sse_done(c.post("/api/agent/stream", json=body, headers=_h("u1")))
    assert again["done"] is True and again["reply"] == first["reply"]
    assert len(reminders) == 1, "the retry ran the turn's tools again"

    # The tap can come long after: the ledger keeps the answer for a day.
    ttl = {i["name"]: i for i in db["agent_turns"].list_indexes()}["created_at_ttl"]
    assert ttl["expireAfterSeconds"] >= 86400


def test_the_same_id_in_another_conversation_is_its_own_turn(env):
    c, _, reminders = env
    cmid = uuid.uuid4().hex
    one = {"message": "أ", "conversation_id": uuid.uuid4().hex, "client_msg_id": cmid}
    two = {"message": "ب", "conversation_id": uuid.uuid4().hex, "client_msg_id": cmid}
    _sse_done(c.post("/api/agent/stream", json=one, headers=_h("u1")))
    reply = _sse_done(c.post("/api/agent/stream", json=two, headers=_h("u1")))
    assert reply["reply"] == "ذكّرتك: ب", "another conversation was answered with this one's reply"
    assert len(reminders) == 2


def test_the_user_line_sent_again_under_its_id_is_kept_once(env):
    c, db, _ = env
    cid, cmid = uuid.uuid4().hex, uuid.uuid4().hex
    line = {"role": "user", "text": "ذكريني بالدوا", "client_msg_id": cmid}
    for _ in range(2):
        r = c.post(f"/api/conversations/{cid}/messages", json=line, headers=_h("u1"))
        assert r.status_code == 200
    msgs = c.get(f"/api/conversations/{cid}", headers=_h("u1")).get_json()["messages"]
    assert [m["text"] for m in msgs] == ["ذكريني بالدوا"]
    # Only within that conversation: the same id in another one is its own line.
    other = uuid.uuid4().hex
    c.post(f"/api/conversations/{other}/messages", json=line, headers=_h("u1"))
    assert len(c.get(f"/api/conversations/{other}", headers=_h("u1")).get_json()["messages"]) == 1


def test_a_stop_finds_the_running_turn_of_its_conversation(env, monkeypatch):
    c, db, _ = env
    from app.api.conversations_api import claim_turn
    from app.brain import stops

    asked = []
    monkeypatch.setattr(stops, "request", lambda uid, thread, partial: asked.append(thread))
    cid, cmid = uuid.uuid4().hex, uuid.uuid4().hex
    assert claim_turn(db, "u1", cmid, cid)[0] == "new"     # still running
    c.post(f"/api/conversations/{cid}/stop", json={"partial": "نص", "client_msg_id": cmid},
           headers=_h("u1"))
    assert asked == [cid], "the running turn was not found under its conversation"
