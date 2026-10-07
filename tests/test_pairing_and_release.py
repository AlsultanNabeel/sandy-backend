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


# T1: actuation asked only whether the device row was the caller's, not whether the node
# still was. A release whose device delete failed (swallowed, «0 removed») went on, and the
# old owner kept moving the neck, the screen and the IR of a robot sold to someone else.

@pytest.fixture
def two_owners():
    import mongomock

    from app import db as appdb
    from app.features import device_store

    d = mongomock.MongoClient().db
    device_store.init_device_store(d)
    node_store.init_node_store(d)
    yield d
    appdb.reset()


def _as(uid):
    from app.utils.user_profiles import active_user_profile_context
    return active_user_profile_context({"chat_id": uid, "relation": "user"})


def test_a_device_left_behind_does_not_drive_a_robot_sold_on(two_owners):
    from app.features import device_store

    d = two_owners
    with _as("seller"):
        d["sandy_nodes"].insert_one({"node_id": "8421", "user_id": "seller"})
        assert device_store.add_device("sandy_head", "رقبة", "dimmer",
                                       {"kind": "node", "node_id": "8421", "output": "servo"})["ok"]
        assert device_store.tenant_owns_topic("sandy/node/8421/servo")
    # The robot changed hands with the seller's row still there.
    d["sandy_nodes"].update_one({"node_id": "8421"}, {"$set": {"user_id": "buyer"}})
    with _as("seller"):
        assert device_store.tenant_owns_topic("sandy/node/8421/servo") is False


def test_a_release_whose_device_delete_fails_stops(two_owners, monkeypatch):
    from pymongo.errors import AutoReconnect

    from app.features import device_store

    d = two_owners
    monkeypatch.setattr(node_store, "_wipe_board", lambda node_id: True)
    with _as("seller"):
        d["sandy_nodes"].insert_one({"node_id": "8421", "user_id": "seller"})
        device_store.add_device("sandy_head", "رقبة", "dimmer",
                                {"kind": "node", "node_id": "8421", "output": "servo"})
        real = device_store._coll

        class _Failing:
            def __init__(self, coll):
                self._coll = coll

            def delete_many(self, *a, **k):
                raise AutoReconnect("database went away")

            def __getattr__(self, name):
                return getattr(self._coll, name)

        monkeypatch.setattr(device_store, "_coll", lambda: _Failing(real()))
        r = node_store.unpair_node("8421")
    assert r["ok"] is False and r["error"] == "release_failed"
    assert d["sandy_nodes"].find_one({"node_id": "8421"})        # still his, to finish later
