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
    from app.brain import stm as g

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
            tv.bump_for("o1", collection="sandy_entries")
            assert tv.version_for("o1") == 1, "a write in the turn was hidden from it"
        # Nothing crosses into the next turn.
        tv.version_for("o1")
        assert len(reads) == 3
    finally:
        tv._coll = orig
