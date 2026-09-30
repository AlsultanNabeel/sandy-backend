"""Chat (plain + stream) and voice run the brain: its tools, its answer."""
from __future__ import annotations

import json

import mongomock
import pytest
from brain_fakes import A, ScriptedModel, brain_db, text_reply  # noqa: F401


def _h(uid="u1"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    from app.brain import loop
    from app.features import usage_store

    calls = []

    def fake_brain(message, **kw):
        calls.append(kw)
        return {"final_response": f"new:{message}"}

    monkeypatch.setattr(loop, "run_turn", fake_brain)
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)
    app = create_app(mongo_db=mongomock.MongoClient().db)
    return app.test_client(), calls


def test_both_chat_routes_run_the_brain(client):
    c, calls = client
    r = c.post("/api/agent", json={"message": "هاي"}, headers=_h())
    assert r.get_json()["reply"] == "new:هاي"
    s = c.post("/api/agent/stream", json={"message": "هاي"}, headers=_h())
    done = [json.loads(line[6:]) for line in s.get_data(as_text=True).splitlines()
            if line.startswith("data: ")][-1]
    assert done["done"] is True and done["reply"] == "new:هاي"
    assert len(calls) == 2 and calls[0]["user_id"] == "u1" and calls[0]["source"] == "web"


def test_a_guest_token_is_refused(client):
    from app.api.auth_handlers import make_token
    c, calls = client
    h = {"Authorization": f"Bearer {make_token('guest')}"}
    assert c.post("/api/agent", json={"message": "هاي"}, headers=h).status_code == 403
    assert c.post("/api/agent/stream", json={"message": "هاي"}, headers=h).status_code == 403
    assert calls == []


def test_stream_route_streams_the_brain_answer(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    from app.brain import model
    from app.features import usage_store

    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)
    monkeypatch.setattr(model, "complete", ScriptedModel(text_reply("أهلين فيك")))
    c = create_app(mongo_db=brain_db).test_client()
    s = c.post("/api/agent/stream", json={"message": "هاي"}, headers=_h())
    events = [json.loads(line[6:]) for line in s.get_data(as_text=True).splitlines()
              if line.startswith("data: ")]
    assert {"text": "أهلين فيك"} in events
    assert events[-1]["done"] is True and events[-1]["reply"] == "أهلين فيك"


class _Types:
    class Tool:
        def __init__(self, function_declarations):
            self.function_declarations = function_declarations


def test_voice_declares_and_runs_the_brain(brain_db):  # noqa: F811
    from app.api.voice_ws import tools as vt
    from app.blocks import items
    from app.utils.user_profiles import active_user_profile_context
    names = {d["name"] for d in vt._build_live_tools(_Types)[0].function_declarations}
    assert {"list_add", "recall", "confirm"} <= names and "task_create" not in names
    out = vt._dispatch_tool("list_add", {"list": "shopping", "text": "خبز"}, "userA")
    assert out["ok"] is True
    with active_user_profile_context(A):
        assert [i["text"] for i in items.list_items("shopping")] == ["خبز"]
