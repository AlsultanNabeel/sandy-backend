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


def test_search_as_you_type_spends_a_bounded_number_of_model_calls(env, monkeypatch):
    """Every keystroke used to embed the query, with no length cap and no limit."""
    from datetime import datetime, timezone

    from app.api import conversations_api
    from app.features import usage_store

    c, _ = env
    # One minute throughout, or a minute boundary mid-test resets the window.
    monkeypatch.setattr(usage_store, "_now",
                        lambda: datetime(2026, 10, 6, 3, 0, 30, tzinfo=timezone.utc))
    embedded = []
    monkeypatch.setattr(conversations_api, "_semantic_hits",
                        lambda uid, q, limit=30: embedded.append(q) or [])
    for n in range(40):
        r = c.get("/api/conversations/search", query_string={"q": "رحلة " * (60 + n)},
                  headers=_h())
        assert r.status_code == 200, "text search must keep answering"
    assert len(embedded) <= conversations_api.SEARCH_EMBEDS_PER_MIN
    assert all(len(q) <= conversations_api.MAX_SEARCH_QUERY for q in embedded)
