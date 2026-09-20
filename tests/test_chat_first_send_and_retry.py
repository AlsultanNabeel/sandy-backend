"""Chat send path: no POST round trip before a new chat's first token, and a
send retried after a network drop never runs the turn twice.

* The app picks a new chat's id itself; the first turn that names it creates
  the conversation for the caller — an id that already belongs to someone else
  is refused, never read or written.
* Each user message carries a `client_msg_id`; a duplicate is answered from the
  turn ledger instead of running the graph (and the meter) again.
"""
from __future__ import annotations

import json
import uuid

import mongomock
import pytest


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.agent import pending_store
    from app.agent.graph import graph as graph_mod
    from app.api.server import create_app
    from app.features import usage_store

    calls = []

    def fake_run_graph(message, **kw):
        calls.append((message, kw.get("conversation_id")))
        return {"reply": f"رد على {message}"}

    monkeypatch.setattr(graph_mod, "run_graph", fake_run_graph)
    monkeypatch.setattr(graph_mod, "get_final_reply", lambda st: {"text": st["reply"]})
    monkeypatch.setattr(pending_store, "load_pending_state", lambda *a, **k: None)
    monkeypatch.setattr(pending_store, "save_pending_state", lambda *a, **k: None)
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)

    db = mongomock.MongoClient().db
    app = create_app(mongo_db=db, semantic_memory_stats_fn=lambda: {})
    return app.test_client(), db, calls


def _h(uid):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


def _sse_done(resp):
    events = [json.loads(line[len("data: "):])
              for line in resp.get_data(as_text=True).splitlines()
              if line.startswith("data: ")]
    return events[-1]


def test_duplicate_client_msg_id_does_not_run_the_graph_twice(env):
    c, _, calls = env
    body = {"message": "مرحبا", "client_msg_id": uuid.uuid4().hex}
    r1 = c.post("/api/agent", json=body, headers=_h("u1"))
    r2 = c.post("/api/agent", json=body, headers=_h("u1"))
    assert r1.status_code == r2.status_code == 200
    assert r2.get_json()["reply"] == r1.get_json()["reply"] == "رد على مرحبا"
    assert len(calls) == 1

    # The stream route shares the ledger and answers a retry with `done`.
    s = c.post("/api/agent/stream", json=body, headers=_h("u1"))
    done = _sse_done(s)
    assert done["done"] is True and done["reply"] == "رد على مرحبا"
    assert len(calls) == 1

    # Keys are per user: the same key from another account is its own turn.
    c.post("/api/agent", json=body, headers=_h("u2"))
    assert len(calls) == 2


def test_duplicate_while_first_run_is_processing_is_not_rerun(env):
    c, db, calls = env
    from app.api.conversations_api import claim_turn

    cmid = uuid.uuid4().hex
    assert claim_turn(db, "u1", cmid) == ("new", None)  # a run in flight
    r = c.post("/api/agent", json={"message": "x", "client_msg_id": cmid}, headers=_h("u1"))
    assert r.status_code == 409 and r.get_json()["error"] == "still_processing"
    assert calls == []


def test_stream_retry_waits_for_the_first_run(env):
    c, db, calls = env
    from app.api.conversations_api import claim_turn, finish_turn

    cmid = uuid.uuid4().hex
    claim_turn(db, "u1", cmid)
    finish_turn(db, "u1", cmid, {"reply": "خلص", "role": "user"})
    done = _sse_done(c.post("/api/agent/stream",
                            json={"message": "x", "client_msg_id": cmid}, headers=_h("u1")))
    assert done == {"reply": "خلص", "role": "user", "done": True}
    assert calls == []


def test_another_users_conversation_id_is_refused(env):
    c, db, calls = env
    cid = uuid.uuid4().hex
    # u1 owns it (created implicitly by their first message).
    assert c.post("/api/conversations/%s/messages" % cid,
                  json={"role": "user", "text": "سر"}, headers=_h("u1")).status_code == 200

    for path in ("/api/agent", "/api/agent/stream"):
        r = c.post(path, json={"message": "hi", "conversation_id": cid}, headers=_h("u2"))
        assert r.status_code == 404, path
    r = c.post(f"/api/conversations/{cid}/messages",
               json={"role": "user", "text": "دخيل"}, headers=_h("u2"))
    assert r.status_code == 404
    assert c.get(f"/api/conversations/{cid}", headers=_h("u2")).status_code == 404
    assert calls == []

    doc = db.conversations.find_one({"_id": cid})
    assert doc["user_id"] == "u1" and [m["text"] for m in doc["messages"]] == ["سر"]
    assert db.conversations.count_documents({}) == 1


def test_first_message_creates_the_conversation_with_a_title(env):
    c, db, calls = env
    cid = uuid.uuid4().hex
    h = _h("u1")

    # The stream may land before the user message's append — either order works.
    done = _sse_done(c.post("/api/agent/stream",
                            json={"message": "خطة السفر", "conversation_id": cid,
                                  "client_msg_id": uuid.uuid4().hex}, headers=h))
    assert done["done"] is True
    assert calls == [("خطة السفر", cid)]
    assert c.post(f"/api/conversations/{cid}/messages",
                  json={"role": "user", "text": "خطة السفر"}, headers=h).status_code == 200
    assert c.post(f"/api/conversations/{cid}/messages",
                  json={"role": "sandy", "text": done["reply"]}, headers=h).status_code == 200

    items = c.get("/api/conversations", headers=h).get_json()["items"]
    assert [(i["id"], i["title"]) for i in items] == [(cid, "خطة السفر")]
    msgs = c.get(f"/api/conversations/{cid}", headers=h).get_json()["messages"]
    assert [(m["role"], m["text"]) for m in msgs] == [
        ("user", "خطة السفر"), ("sandy", "رد على خطة السفر")]

    # Append first, then the stream: still exactly one conversation.
    cid2 = uuid.uuid4().hex
    c.post(f"/api/conversations/{cid2}/messages",
           json={"role": "user", "text": "ثاني"}, headers=h)
    c.post("/api/agent", json={"message": "ثاني", "conversation_id": cid2}, headers=h)
    assert db.conversations.count_documents({"user_id": "u1"}) == 2

    # The explicit POST still works.
    r = c.post("/api/conversations", json={}, headers=h)
    assert r.status_code == 200 and r.get_json()["id"]


def test_malformed_conversation_id_is_refused(env):
    c, _, calls = env
    r = c.post("/api/agent", json={"message": "x", "conversation_id": "{$ne: 1}"},
               headers=_h("u1"))
    assert r.status_code == 404 and calls == []
