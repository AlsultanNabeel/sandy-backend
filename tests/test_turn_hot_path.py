"""Regressions for the chat-turn hot path (Sept 2026 pass).

What the person waits for between sending a message and the first word of the
reply. Each test pins one round trip or model cost that used to sit there.
"""
from __future__ import annotations

from datetime import datetime, timezone

import mongomock
import pytest


OWNER = {"user_id": "o1", "chat_id": "o1", "name": "O", "is_owner": True,
         "is_guest": False, "permissions": "all", "relation": "owner"}


@pytest.fixture()
def db():
    import app.db as appdb

    database = mongomock.MongoClient()["t"]
    appdb.configure(database)
    try:
        yield database
    finally:
        appdb.reset()


def test_the_thread_is_not_read_twice_when_the_recent_read_has_it(db):
    """The cross-channel read already returns this thread's document; reading
    it again with `find_one` was one more serial round trip per message."""
    import app.agent.graph.graph as g

    now = datetime.now(timezone.utc)
    db["sandy_stm"].insert_one({"key": "c1:u1", "user_id": "u1", "updated_at": now,
                                "history": [{"role": "user", "content": "هاي",
                                             "timestamp": "1"}]})
    threads: dict = {}
    turns = g.recent_turns_for_user("u1", threads_out=threads)
    assert turns and threads["c1:u1"] == turns


def test_the_tenant_version_is_read_once_per_turn_and_writes_still_show(db):
    from app.utils import tenant_version as tv

    reads = []
    real = db["sandy_cache_stamps"].find_one

    class _Spy:
        def __getattr__(self, name):
            return getattr(db["sandy_cache_stamps"], name)

        def find_one(self, *a, **kw):
            reads.append(1)
            return real(*a, **kw)

    orig = tv._coll
    tv._coll = lambda: _Spy()
    try:
        with tv.turn_scope():
            assert tv.version_for("o1") == 0
            assert tv.version_for("o1") == 0
            assert len(reads) == 1, "the same turn asked Mongo twice"
            tv.bump_for("o1", collection="sandy_tasks")
            assert tv.version_for("o1") == 1, "a write in the turn was hidden from it"
        # Nothing crosses into the next turn.
        tv.version_for("o1")
        assert len(reads) == 3
    finally:
        tv._coll = orig


def test_a_failed_embedding_is_not_retried_by_each_search(db, monkeypatch):
    """One failed embedding used to become three: the turn's, then one more
    inside each search — each with its own timeout on a degraded endpoint."""
    import app.agent.semantic_memory as sem
    from app.utils import user_profiles

    calls = []
    monkeypatch.setattr(sem, "_embed", lambda text: calls.append(text))
    db["sandy_facts"].insert_one({"chat_id": "o1", "text": "بقرا كتاب", "usage_count": 0})
    with user_profiles.active_user_profile_context(OWNER):
        sem.search_memory_for_turn("كتاب", "o1")
    assert len(calls) == 1


def test_the_router_is_told_to_call_a_tool_not_write_a_reply(monkeypatch):
    """Chat is a tool. Letting the router answer in text made it write a whole
    reply that was thrown away before the real one was generated."""
    from app.agent.agents import fc_router
    from app.agent.graph.state import create_initial_state

    seen = {}

    class _Client:
        def complete_with_tools(self, system, user, tools, **kw):
            seen.update(kw)
            return None

    monkeypatch.setattr(fc_router, "AzureIntentClient", _Client)
    monkeypatch.setattr(fc_router, "_device_catalog", lambda state: "")
    state = create_initial_state(message="مرحبا", user_id="u1", chat_id="u1")
    out = fc_router.route_with_fc(state, [{"name": "chat_respond"}])
    assert seen.get("tool_choice") == "required"
    assert out["function_call"]["name"] == "chat_respond"
