"""SANDY_NEW_AGENT: off = the old graph and old voice tools, on = the brain."""
from __future__ import annotations

import json
import os

import mongomock
import pytest
from brain_fakes import A, ScriptedModel, brain_db, text_reply  # noqa: F401


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.agent import pending_store
    from app.agent.graph import graph as graph_mod
    from app.api.server import create_app
    from app.brain import loop
    from app.features import usage_store

    calls = []

    def fake_graph(message, **kw):
        calls.append("graph")
        return {"final_response": f"old:{message}"}

    def fake_brain(message, **kw):
        calls.append("brain")
        return {"final_response": f"new:{message}"}

    monkeypatch.setattr(graph_mod, "run_graph", fake_graph)
    monkeypatch.setattr(loop, "run_turn", fake_brain)
    monkeypatch.setattr(pending_store, "load_pending_state", lambda *a, **k: None)
    monkeypatch.setattr(pending_store, "save_pending_state", lambda *a, **k: None)
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)
    app = create_app(mongo_db=mongomock.MongoClient().db, semantic_memory_stats_fn=lambda: {})
    return app.test_client(), calls


def _h(uid="u1"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


@pytest.mark.skipif("SANDY_NEW_AGENT" in os.environ, reason="the flag is set in this environment")
def test_the_flag_defaults_off():
    from app import config
    from app.brain import enabled
    assert config.SANDY_NEW_AGENT is False and enabled() is False


@pytest.mark.parametrize("flag, expected", [(False, "graph"), (True, "brain")])
def test_chat_routes_follow_the_flag(client, monkeypatch, flag, expected):
    c, calls = client
    monkeypatch.setattr("app.config.SANDY_NEW_AGENT", flag)
    r = c.post("/api/agent", json={"message": "هاي"}, headers=_h())
    assert r.get_json()["reply"].startswith("new:" if flag else "old:")
    s = c.post("/api/agent/stream", json={"message": "هاي"}, headers=_h())
    done = [json.loads(line[6:]) for line in s.get_data(as_text=True).splitlines()
            if line.startswith("data: ")][-1]
    assert done["done"] is True and done["reply"].startswith("new:" if flag else "old:")
    assert calls == [expected, expected]


def test_stream_route_streams_the_brain_answer(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    from app.brain import model
    from app.features import usage_store

    monkeypatch.setattr("app.config.SANDY_NEW_AGENT", True)
    monkeypatch.setattr(usage_store, "check_and_record", lambda *a, **k: None)
    monkeypatch.setattr(model, "complete", ScriptedModel(text_reply("أهلين فيك")))
    c = create_app(mongo_db=brain_db, semantic_memory_stats_fn=lambda: {}).test_client()
    s = c.post("/api/agent/stream", json={"message": "هاي"}, headers=_h())
    events = [json.loads(line[6:]) for line in s.get_data(as_text=True).splitlines()
              if line.startswith("data: ")]
    assert {"text": "أهلين فيك"} in events
    assert events[-1]["done"] is True and events[-1]["reply"] == "أهلين فيك"


class _Types:
    class Tool:
        def __init__(self, function_declarations):
            self.function_declarations = function_declarations


def test_voice_declares_the_old_registry_with_the_flag_off(monkeypatch):
    from app.api.voice_ws import tools as vt
    monkeypatch.setattr("app.config.SANDY_NEW_AGENT", False)
    names = {d["name"] for d in vt._build_live_tools(_Types)[0].function_declarations}
    assert "task_create" in names and "list_add" not in names
    assert vt._make_dispatcher() != vt._BRAIN_DISPATCHER


def test_voice_declares_and_runs_the_brain_with_the_flag_on(monkeypatch, brain_db):  # noqa: F811
    from app.api.voice_ws import tools as vt
    from app.blocks import items
    from app.utils.user_profiles import active_user_profile_context
    monkeypatch.setattr("app.config.SANDY_NEW_AGENT", True)
    names = {d["name"] for d in vt._build_live_tools(_Types)[0].function_declarations}
    assert {"list_add", "recall", "confirm"} <= names and "task_create" not in names
    dispatcher = vt._make_dispatcher()
    assert dispatcher == vt._BRAIN_DISPATCHER
    out = vt._dispatch_tool(dispatcher, "list_add", {"list": "shopping", "text": "خبز"}, "userA")
    assert out["ok"] is True
    with active_user_profile_context(A):
        assert [i["text"] for i in items.list_items("shopping")] == ["خبز"]
