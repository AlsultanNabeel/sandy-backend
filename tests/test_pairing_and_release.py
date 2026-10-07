"""Pairing, one robot per account, and letting a robot go (batch 7)."""
from __future__ import annotations

import pytest
from pymongo.errors import OperationFailure

from app.features import node_store


# T11: the three indexes were built in one try, so the first failing skipped the
# uniqueness index, and two accounts pairing at the same moment could both win.

def test_one_failed_index_does_not_skip_the_others():
    built = []

    class _Coll:
        def create_index(self, keys, **kw):
            if not built and not kw.get("name"):
                built.append("failed")
                raise OperationFailure("index build failed")
            built.append(kw.get("name") or keys[0][0])

    class _Db(dict):
        def __getitem__(self, name):
            return _Coll()

    node_store.init_node_store(_Db())
    assert built == ["failed", "code_hash", "node_id_owner_unique"]


# T13: two workers provisioning the same heartbeat: the loser got an uncaught duplicate
# error, which skipped the rest of the parts that round (and a hand-made add answered 500).

def test_a_device_added_at_the_same_moment_is_exists_not_an_error(monkeypatch):
    import mongomock

    from app import db as appdb
    from app.features import device_store
    from app.utils.user_profiles import active_user_profile_context

    d = mongomock.MongoClient().db
    device_store.init_device_store(d)
    try:
        d["sandy_nodes"].insert_one({"node_id": "n1", "user_id": "u1"})
        with active_user_profile_context({"chat_id": "u1", "relation": "user"}):
            # The other worker's insert lands between this one's check and its insert.
            real = device_store._coll

            class _Racing:
                """The scoped collection, whose check ran before the other insert."""
                def __init__(self, coll):
                    self._coll = coll

                def find_one(self, *a, **k):
                    d["sandy_devices"].insert_one({"user_id": "u1", "name": "lamp"})
                    return None

                def __getattr__(self, name):
                    return getattr(self._coll, name)

            def racing():
                return _Racing(real())

            monkeypatch.setattr(device_store, "_coll", racing)
            r = device_store.add_device("lamp", "لمبة", "switch",
                                        {"kind": "node", "node_id": "n1", "output": "relay"})
        assert r == {"ok": False, "error": "exists"}
    finally:
        appdb.reset()
