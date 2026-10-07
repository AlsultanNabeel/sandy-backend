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
                     "last_seen", "since"]


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


# F28: the erase went once, unkept, to a board on a clean session that takes it for five
# minutes; after that its key was revoked, its node deleted and its heartbeats dropped. A
# robot off at release was never wiped and kept the seller's Wi-Fi and broker login, while
# the app said done.

SHARED = b"shared-test-key"


@pytest.fixture
def released(two_owners, monkeypatch):
    """u1's robot, heard on «Home» after 7 restarts, given its own key, then released while
    it was off; returns what reaches the broker after that."""
    from app.api.voice_ws import _config
    from app.features import device_keys
    from app.integrations import room_device

    monkeypatch.setattr(_config, "_HMAC_KEY", SHARED)
    sent = []

    class _Broker:
        def publish_service(self, topic, payload):
            sent.append((topic, payload))
            return True

        def send_to_topic(self, topic, payload):
            return True

    monkeypatch.setattr(room_device, "get_room_device_client", lambda: _Broker())
    with _as("u1"):
        node_store.pair_node("SANDY-8421")
        node_store.ingest_status("sandy8421", True, telemetry={"boots": 7, "ssid": "Home"})
        device_keys.open_enrolment("sandy8421")
        own = device_keys.issue_key("sandy8421")
        _beat({"online": False})                          # its MQTT will: it went off
        out = node_store.unpair_node("sandy8421")
    sent.clear()
    return {"out": out, "sent": sent, "own": bytes.fromhex(own), "db": two_owners}


def _signed_by(command, key, node_id="sandy8421"):
    import hashlib
    import hmac

    _, ms, mac = command.split(":")
    return hmac.compare_digest(
        mac, hmac.new(key, f"factory_reset|{node_id}|{ms}".encode(), hashlib.sha256).hexdigest())


def test_a_robot_off_at_release_is_wiped_when_it_comes_back(released):
    assert released["out"]["board_wiped"] is False and released["out"]["erase_pending"]
    _beat({"online": True, "boots": 7, "ssid": "Home"})   # back, still on the seller's Wi-Fi
    commands = [p for t, p in released["sent"] if t == "sandy/node/sandy8421/factory_reset"]
    # It checks with one key, its own if it kept it, else the shared: both go.
    assert len(commands) == 2
    assert _signed_by(commands[0], released["own"]) and _signed_by(commands[1], SHARED)


def test_it_goes_again_at_most_once_a_minute(released):
    from datetime import datetime, timedelta, timezone

    _beat({"online": True, "boots": 7, "ssid": "Home"})
    _beat({"online": True, "boots": 7, "ssid": "Home"})
    assert len(released["sent"]) == 2
    released["db"]["node_pending_erase"].update_one({"_id": "sandy8421"}, {"$set": {
        "sent_at": datetime.now(timezone.utc) - timedelta(minutes=2)}})
    _beat({"online": True, "boots": 7, "ssid": "Home"})
    assert len(released["sent"]) == 4


@pytest.mark.parametrize("after", [{"boots": 1, "ssid": "Home"}, {"boots": 9, "ssid": "Buyer"}])
def test_a_board_that_shows_it_was_wiped_is_left_alone(released, after):
    _beat({"online": True, **after})          # restarts counted from one again, or a new network
    _beat({"online": True, **after})
    assert released["sent"] == []
    assert released["db"]["node_pending_erase"].count_documents({}) == 0


def test_never_to_a_board_paired_to_another_account(released, monkeypatch):
    # The buyer pairs it (presence shown on its face) before it was ever heard again.
    with _as("buyer"):
        monkeypatch.setattr(node_store, "_wipe_board", lambda node_id: True)
        assert node_store.pair_node("SANDY-8421")["ok"]
    assert released["db"]["node_pending_erase"].count_documents({}) == 0
    _beat({"online": True, "boots": 7, "ssid": "Home"})
    assert released["sent"] == []


def test_never_to_a_board_paired_while_the_erase_was_on_its_way(released):
    # The pending row is still there, but the board belongs to an account by the time the
    # send checks: nothing goes, and the row is dropped.
    released["db"]["sandy_nodes"].insert_one({"node_id": "sandy8421", "user_id": "buyer"})
    node_store._erase_if_pending("sandy8421", {"boots": 7, "ssid": "Home"})
    assert released["sent"] == []
    assert released["db"]["node_pending_erase"].count_documents({}) == 0


# T12: a time up to two minutes ahead was accepted while a signature was remembered three
# minutes, so the same upload could be replayed in its fourth minute; a database error let
# a replay through; a body with no length was read whole before the signature was checked.

@pytest.fixture
def cam(monkeypatch):
    import mongomock
    from flask import Flask

    from app import db as appdb
    from app.api import devices_api
    from app.api.voice_ws import _config as vcfg

    d = mongomock.MongoClient().db
    appdb.configure(d)
    monkeypatch.setattr(vcfg, "_HMAC_KEY", SHARED)
    import app.integrations.camera_client as cc
    monkeypatch.setattr(cc, "store_snapshot", lambda *a, **k: None)
    d["sandy_nodes"].insert_one({"node_id": "8421", "user_id": "owner-1"})
    app = Flask(__name__)
    devices_api.register_devices_api(app, d)
    yield app.test_client(), d
    appdb.reset()


JPEG = b"\xff\xd8" + b"x" * 200


def _upload(c, ahead_ms=0, body=JPEG):
    import hashlib
    import hmac
    import time

    ts = str(int(time.time() * 1000) + ahead_ms)
    sig = hmac.new(SHARED, f"8421live{ts}".encode(), hashlib.sha256).hexdigest()
    return c.post("/api/cam/upload", data=body, headers={
        "X-Sandy-Node": "8421", "X-Sandy-Req": "live", "X-Sandy-Ts": ts,
        "X-Sandy-Sig": sig, "Content-Type": "image/jpeg"})


def test_a_time_ahead_is_allowed_thirty_seconds(cam):
    c, _ = cam
    assert _upload(c, ahead_ms=20_000).status_code == 200
    assert _upload(c, ahead_ms=60_000).get_json()["error"] == "stale"


def test_a_signature_is_remembered_past_the_whole_window():
    from datetime import timedelta

    from app.api import devices_api

    accepted_for = timedelta(milliseconds=devices_api._CAM_PAST_MS + devices_api._CAM_FUTURE_MS)
    assert devices_api._CAM_NONCE_KEPT > accepted_for


def test_a_database_error_is_refused_not_let_through(cam, monkeypatch):
    from pymongo.errors import AutoReconnect

    from app.api import devices_api

    c, d = cam

    class _Down:
        def insert_one(self, *a, **k):
            raise AutoReconnect("down")

    real = d.__class__.__getitem__
    monkeypatch.setattr(d.__class__, "__getitem__",
                        lambda self, name: _Down() if name == devices_api._CAM_NONCES
                        else real(self, name))
    assert _upload(c).status_code == 503


def test_a_body_is_read_only_up_to_the_cap(cam, monkeypatch):
    """`get_data` reads the whole body, whatever its size, when no length came with it;
    the upload reads the stream up to its cap instead (a test client cannot send a body
    with no length, so the call itself is what is pinned)."""
    import flask

    from app.api import devices_api

    c, _ = cam
    monkeypatch.setattr(flask.Request, "get_data",
                        lambda self, *a, **k: pytest.fail("the whole body was read"))
    monkeypatch.setattr(devices_api, "_CAM_MAX_UPLOAD_BYTES", 300)
    assert _upload(c).status_code == 200
    monkeypatch.setattr(devices_api, "_CAM_MAX_UPLOAD_BYTES", 100)
    r = c.post("/api/cam/upload", data=JPEG, headers={"X-Sandy-Node": "8421"})
    assert r.status_code == 400                   # headers first, nothing read


# The broker logins (the owner's decision): only a paired board is handed its own login,
# a release lists it for the owner to revoke on the broker, and the list is on his diagnose.
# A new board must still pair: it reaches the broker with its factory login, heartbeats,
# and shows the code, before any account is behind it.

@pytest.fixture
def fleet(two_owners, monkeypatch):
    import hashlib
    import hmac
    import json
    import time

    from app import config
    from app.api.voice_ws import _config as vcfg
    from app.api.voice_ws import session as sess
    from app.features import broker_creds, pair_presence
    from app.integrations import room_device

    monkeypatch.setenv("JWT_SECRET", "x" * 40)
    monkeypatch.setattr(vcfg, "_HMAC_KEY", SHARED)
    monkeypatch.setattr(sess, "_HMAC_KEY", SHARED)
    monkeypatch.setattr(sess, "set_voice_identity", lambda *_: None)
    monkeypatch.setattr(sess, "set_voice_channel", lambda *_: None)
    monkeypatch.setattr(config, "SANDY_BROKER_CREDS",
                        json.dumps({"sandy8421": {"user": "node-8421", "pass": "p"}}))
    monkeypatch.setattr(config, "SANDY_OWNER_ACCOUNTS", "owner")
    broker_creds.reset_cache()
    shown = []
    monkeypatch.setattr(pair_presence, "_publish",
                        lambda node_id, code: shown.append(code) or True)

    class _Broker:
        def publish_service(self, topic, payload):
            return True

        def send_to_topic(self, topic, payload):
            return True

    monkeypatch.setattr(room_device, "get_room_device_client", lambda: _Broker())

    class _WS:
        def __init__(self, hello):
            self._hello, self.sent = json.dumps(hello), []

        def receive(self, timeout=None):
            return self._hello

        def send(self, data):
            self.sent.append(json.loads(data) if data.startswith("{") else data)

    def handshake():
        ts = int(time.time() * 1000)
        mac = hmac.new(SHARED, f"sandy8421{ts}".encode(), hashlib.sha256).hexdigest()
        ws = _WS({"type": "hello", "device_id": "sandy8421", "ts": ts, "hmac": mac})
        sess._authenticate(ws, "test")
        return next(m for m in ws.sent if isinstance(m, dict) and m.get("type") == "auth_ok")

    from app.api.auth_handlers import make_token
    from app.api.server import create_app

    c = create_app(mongo_db=two_owners).test_client()
    yield {"c": c, "handshake": handshake, "shown": shown,
           "h": lambda uid: {"Authorization": f"Bearer {make_token('user', uid)}"}}
    broker_creds.reset_cache()


def test_a_new_board_pairs_from_its_first_heartbeat_to_its_own_login(fleet):
    c, h = fleet["c"], fleet["h"]("u1")
    # Out of the box: on the broker with its factory login, heartbeating, nobody's yet.
    _beat({"online": True})
    # Woken before pairing: no login of its own is handed to a board nobody paired.
    assert "broker" not in fleet["handshake"]()
    # The app starts pairing: the code goes to its face.
    r = c.post("/api/nodes/pair", json={"code": "SANDY-8421"}, headers=h)
    assert r.status_code == 202 and len(fleet["shown"]) == 1
    # The owner types what it shows.
    r = c.post("/api/nodes/pair/confirm",
               json={"code": "SANDY-8421", "presence": fleet["shown"][0]}, headers=h)
    assert r.status_code == 200 and r.get_json()["node_id"] == "sandy8421"
    # Paired: the next handshake hands it its own login (and its own voice key).
    reply = fleet["handshake"]()
    assert reply["broker"] == {"user": "node-8421", "pass": "p"} and reply.get("device_key")


def test_a_release_lists_its_login_for_the_owner_only(fleet, monkeypatch):
    from app import config
    from app.features import broker_creds

    c = fleet["c"]
    with _as("u1"):
        node_store.pair_node("SANDY-8421")
        node_store.unpair_node("sandy8421")
    owner = c.get("/api/diagnose", headers=fleet["h"]("owner")).get_json()
    assert owner["broker_logins_to_revoke"][0]["user"] == "node-8421"
    assert "broker_logins_to_revoke" not in c.get(
        "/api/diagnose", headers=fleet["h"]("u1")).get_json()
    # Revoked on the broker and its row removed from the table: it leaves the list.
    monkeypatch.setattr(config, "SANDY_BROKER_CREDS", "{}")
    broker_creds.reset_cache()
    assert c.get("/api/diagnose", headers=fleet["h"]("owner")).get_json()[
        "broker_logins_to_revoke"] == []
