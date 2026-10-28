"""The owner's trace and cost pages (`api/owner_api.py`): the owner only, everyone else 404."""
from __future__ import annotations

import mongomock
import pytest
from cryptography.fernet import Fernet

OWNER = "owner1"


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app import config
    from app.api.server import create_app
    from app.utils import ltm_crypto

    monkeypatch.setattr(config, "SANDY_OWNER_ACCOUNTS", OWNER)
    monkeypatch.setattr(ltm_crypto, "_fernet", Fernet(Fernet.generate_key()))
    monkeypatch.setattr(ltm_crypto, "_init_attempted", True)
    db = mongomock.MongoClient().db
    return create_app(mongo_db=db).test_client(), db


def _h(uid):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


def _turn(user):
    from app.features import trace_store
    t = trace_store.Trace(user, "chat")
    t.add_model_call("azure", "gpt-4.1", tokens_in=100, tokens_out=10)
    return t.finish(request="سؤال", reply="جواب", routed_by="brain")


@pytest.mark.parametrize("path", ["/api/owner/traces", "/api/owner/traces/x", "/api/owner/costs"])
def test_anyone_but_the_owner_gets_nothing(env, path):
    c, _ = env
    assert c.get(path, headers=_h("u2")).status_code == 404
    assert c.get(path).status_code == 401


def test_the_owner_lists_and_opens_turns(env):
    c, _ = env
    mine, theirs = _turn(OWNER), _turn("u2")
    rows = c.get("/api/owner/traces?limit=10", headers=_h(OWNER)).get_json()["traces"]
    assert {r["_id"] for r in rows} == {mine, theirs}
    assert all("request" not in r for r in rows)
    own = c.get(f"/api/owner/traces/{mine}", headers=_h(OWNER)).get_json()
    assert own["request"] == "سؤال" and own["reply"] == "جواب"
    other = c.get(f"/api/owner/traces/{theirs}", headers=_h(OWNER)).get_json()
    assert other["request"] is None and other["tokens_in"] == 100
    assert c.get("/api/owner/traces/nope", headers=_h(OWNER)).status_code == 404


def test_the_owner_sees_the_costs(env):
    c, _ = env
    _turn(OWNER)
    _turn("u2")
    r = c.get("/api/owner/costs?days=7", headers=_h(OWNER)).get_json()
    assert r["days"] == 7 and {u["user_id"] for u in r["by_user"]} == {OWNER, "u2"}
    assert set(r) == {"days", "total_usd", "by_user", "by_source", "by_task"}


def test_bad_numbers_are_refused_plainly(env):
    c, _ = env
    r = c.get("/api/owner/costs?days=abc", headers=_h(OWNER))
    assert r.status_code == 400 and r.get_json()["message"]
