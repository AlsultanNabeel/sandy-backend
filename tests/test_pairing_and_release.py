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
            built.append(kw.get("name") or (keys if isinstance(keys, str) else keys[0][0]))

    class _Db(dict):
        def __getitem__(self, name):
            return _Coll()

    node_store.init_node_store(_Db())
    assert built == ["failed", "code_hash", "node_id_owner_unique", "one_robot_per_account",
                     "last_seen"]


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


# T2: every part has a fixed name per account, so a second robot on the same account found
# the first one's names and got no device at all: no control, no voice, no IR, in silence.
# The owner's decision: one robot per account, the second refused in so many words.

def test_a_second_robot_is_refused_and_the_first_still_pairs_again(two_owners):
    with _as("u1"):
        assert node_store.pair_node("SANDY-8421")["ok"]
        assert node_store.pair_precheck("SANDY-9999")["state"] == "one_robot"
        assert node_store.pair_node("SANDY-9999") == {"ok": False, "error": "one_robot"}
        # The same robot again (its camera and room node share its id), and after a release.
        assert node_store.pair_node("SANDY-8421")["already"] is True
        assert node_store.unpair_node("sandy8421")["ok"]
        assert node_store.pair_node("SANDY-9999")["ok"]


def test_two_robots_at_the_same_moment_one_wins(two_owners, monkeypatch):
    with _as("u1"):
        assert node_store.pair_node("SANDY-8421")["ok"]
        # The second pairing's check ran before the first one's insert landed.
        real, calls = node_store._has_another_robot, []

        def raced(coll, node_id):
            calls.append(node_id)
            return False if len(calls) == 1 else real(coll, node_id)

        monkeypatch.setattr(node_store, "_has_another_robot", raced)
        assert node_store.pair_node("SANDY-9999") == {"ok": False, "error": "one_robot"}
        assert two_owners["sandy_nodes"].count_documents({"user_id": "u1"}) == 1


def test_the_app_is_told_before_any_code_goes_to_the_robot(two_owners, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    from app.api.auth_handlers import make_token
    from app.api.server import create_app
    from app.features import pair_presence

    started = []
    monkeypatch.setattr(pair_presence, "start", lambda *a: started.append(a) or {"ok": True})
    with _as("u1"):
        node_store.pair_node("SANDY-8421")
    c = create_app(mongo_db=two_owners).test_client()
    r = c.post("/api/nodes/pair", json={"code": "SANDY-9999"},
               headers={"Authorization": f"Bearer {make_token('user', 'u1')}"})
    assert r.status_code == 409 and r.get_json()["error"] == "one_robot" and started == []


# T10: the heartbeat is retained on the broker, so every server restart got each board's
# last «online» again and stamped last_seen now: a board gone for days read «seen now».

def test_a_retained_heartbeat_does_not_move_last_seen(two_owners):
    import json
    from datetime import datetime, timedelta, timezone

    from app.integrations import mqtt_ingest

    long_ago = datetime.now(timezone.utc) - timedelta(days=3)
    two_owners["sandy_nodes"].insert_one({"node_id": "8421", "user_id": "u1",
                                          "online": True, "last_seen": long_ago})
    beat = json.dumps({"online": True}).encode()
    mqtt_ingest._handle_message("sandy/node/8421/status", beat, retained=True)
    seen = two_owners["sandy_nodes"].find_one({"node_id": "8421"})["last_seen"]
    assert abs((seen.replace(tzinfo=timezone.utc) - long_ago).total_seconds()) < 1
    mqtt_ingest._handle_message("sandy/node/8421/status", beat)          # the board, live
    seen = two_owners["sandy_nodes"].find_one({"node_id": "8421"})["last_seen"]
    assert datetime.now(timezone.utc) - seen.replace(tzinfo=timezone.utc) < timedelta(seconds=5)


def test_the_retained_flag_reaches_the_handler(monkeypatch):
    from app.integrations import mqtt_ingest

    got = []

    class _Pool:
        _work_queue = type("Q", (), {"qsize": staticmethod(lambda: 0)})()

        def submit(self, fn, *args):
            got.append(args)

    monkeypatch.setattr(mqtt_ingest, "_INGEST", _Pool())
    msg = type("M", (), {"topic": "sandy/node/8421/status", "payload": b"{}", "retain": True})()
    mqtt_ingest._on_message(None, None, msg)
    assert got == [("sandy/node/8421/status", b"{}", True)]


# F20: «sent» for the presence code meant only that the broker took it, and the server
# dropped an unpaired board's heartbeats, so it never knew whether the robot was there: a
# robot off, on its setup network or in safe mode never showed the code, and the app said
# «look at her screen» for five minutes, then «expired».

@pytest.fixture
def pairing(two_owners, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    from app.api.auth_handlers import make_token
    from app.api.server import create_app
    from app.features import pair_presence

    shown = []
    monkeypatch.setattr(pair_presence, "_publish",
                        lambda node_id, code: shown.append((node_id, code)) or True)
    c = create_app(mongo_db=two_owners).test_client()
    h = {"Authorization": f"Bearer {make_token('user', 'u1')}"}
    return c, h, shown


def _beat(body, retained=False):
    import json

    from app.integrations import mqtt_ingest
    mqtt_ingest._handle_message("sandy/node/sandy8421/status", json.dumps(body).encode(),
                                retained=retained)


def _pair(c, h):
    return c.post("/api/nodes/pair", json={"code": "SANDY-8421"}, headers=h)


def test_a_robot_never_heard_gets_no_code_and_the_app_is_told(pairing):
    c, h, shown = pairing
    r = _pair(c, h)
    assert r.status_code == 409 and r.get_json()["error"] == "not_connected" and shown == []


@pytest.mark.parametrize("last", [{"online": False}, {"online": True, "safe": True}])
def test_a_robot_that_went_or_is_in_safe_mode_gets_no_code(pairing, last):
    c, h, shown = pairing
    _beat({"online": True})
    _beat(last)
    assert _pair(c, h).get_json()["error"] == "not_connected" and shown == []


def test_a_heartbeat_half_a_minute_old_or_retained_is_not_there(pairing, two_owners):
    from datetime import datetime, timedelta, timezone

    c, h, shown = pairing
    _beat({"online": True}, retained=True)           # the broker's copy, at a server restart
    assert _pair(c, h).get_json()["error"] == "not_connected"
    _beat({"online": True})
    two_owners["node_sightings"].update_one({"_id": "sandy8421"}, {"$set": {
        "last_seen": datetime.now(timezone.utc) - timedelta(seconds=40)}})
    assert _pair(c, h).get_json()["error"] == "not_connected" and shown == []


def test_a_robot_heard_just_now_gets_its_code(pairing):
    c, h, shown = pairing
    _beat({"online": True})
    r = _pair(c, h)
    assert r.status_code == 202 and shown and shown[0][0] == "sandy8421"
