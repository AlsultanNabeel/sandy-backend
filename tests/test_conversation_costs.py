"""Model calls made for the chat list, not the chat: one title try a conversation, and
search that cannot spend a model call per keystroke without limit."""
from __future__ import annotations

import mongomock
import pytest


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    from app.utils import thread_pool

    monkeypatch.setattr(thread_pool, "submit_background",
                        lambda fn, *a, _label=None, **k: fn(*a, **k))
    db = mongomock.MongoClient().db
    return create_app(mongo_db=db).test_client(), db


def _h(uid="u1"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


def test_a_title_is_asked_for_once_even_when_it_fails(env, monkeypatch):
    from app.integrations import openai_client

    c, _ = env
    asked = []

    def _down():
        def _call(**kw):
            asked.append(kw["messages"][-1]["content"])
            raise RuntimeError("model down")
        return _call
    monkeypatch.setattr(openai_client, "chat_fn", _down)

    cid = c.post("/api/conversations", json={}, headers=_h()).get_json()["id"]
    r = c.post(f"/api/conversations/{cid}/messages", json={"role": "user", "text": "مرحبا " * 3000},
               headers=_h())
    assert r.status_code == 200
    for _ in range(3):
        c.post(f"/api/conversations/{cid}/messages", json={"role": "sandy", "text": "أهلين " * 3000},
               headers=_h())
    assert len(asked) == 1, f"{len(asked)} title calls for one conversation"
    assert len(asked[0]) < 1200, "the whole exchange was sent to name it"
