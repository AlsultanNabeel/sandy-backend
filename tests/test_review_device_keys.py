"""Per-board voice keys: enrol on the shared key, then only the board's own."""
import hashlib
import hmac
import json
import time

import mongomock
import pytest

from app import db as appdb
from app.api.voice_ws import session as sess

SHARED = b"shared-test-key"


class _WS:
    def __init__(self, hello):
        self._hello = json.dumps(hello)
        self.sent = []

    def receive(self, timeout=None):
        return self._hello

    def send(self, data):
        self.sent.append(json.loads(data) if data.startswith("{") else data)


def _hello(device_id, key, kv=None):
    ts = int(time.time() * 1000)
    msg = {"type": "hello", "device_id": device_id, "ts": ts,
           "hmac": hmac.new(key, f"{device_id}{ts}".encode(), hashlib.sha256).hexdigest()}
    if kv:
        msg["kv"] = kv
    return msg


@pytest.fixture
def db(monkeypatch):
    d = mongomock.MongoClient().db
    appdb.configure(d)
    monkeypatch.setattr(sess, "_HMAC_KEY", SHARED)
    monkeypatch.setattr(sess, "set_voice_identity", lambda *_: None)
    monkeypatch.setattr(sess, "set_voice_channel", lambda *_: None)
    d["sandy_nodes"].insert_one({"node_id": "8421", "user_id": "owner-1"})
    from app.features.device_keys import open_enrolment
    open_enrolment("8421")          # the owner just paired it
    yield d
    appdb.reset()


def _auth(hello):
    ws = _WS(hello)
    return sess._authenticate(ws, "test"), ws.sent[-1]


def test_enrol_then_only_the_own_key_works(db):
    ok, reply = _auth(_hello("8421", SHARED))
    assert ok and reply["type"] == "auth_ok"
    own = bytes.fromhex(reply["device_key"])

    # Retried before storing: the same key again, not a new one.
    ok, again = _auth(_hello("8421", SHARED))
    assert ok and again["device_key"] == reply["device_key"]

    ok, reply = _auth(_hello("8421", own, kv=2))
    assert ok and "device_key" not in reply

    ok, reply = _auth(_hello("8421", SHARED))
    assert not ok and reply["msg"] == "auth_fail", "shared key still impersonates"


def test_unpaired_board_gets_no_key(db):
    ok, reply = _auth(_hello("9999", SHARED))
    assert ok and "device_key" not in reply


def test_revoked_key_is_reported_so_the_board_re_enrols(db):
    ok, reply = _auth(_hello("8421", SHARED))
    own = bytes.fromhex(reply["device_key"])
    _auth(_hello("8421", own, kv=2))
    from app.features.device_keys import revoke_key
    revoke_key("8421")
    ok, reply = _auth(_hello("8421", own, kv=2))
    assert not ok and reply["msg"] == "key_unknown"
    ok, reply = _auth(_hello("8421", SHARED))
    assert ok and "device_key" not in reply, "a key handed out with nobody pairing"
    from app.features.device_keys import open_enrolment
    open_enrolment("8421")          # paired again
    ok, reply = _auth(_hello("8421", SHARED))
    assert ok and reply.get("device_key")


def test_wrong_own_key_is_refused(db):
    _auth(_hello("8421", SHARED))
    ok, reply = _auth(_hello("8421", b"x" * 32, kv=2))
    assert not ok and reply["msg"] == "auth_fail"


def test_no_key_outside_the_pairing_window(db):
    from datetime import datetime, timedelta, timezone
    db["sandy_device_keys"].update_one(
        {"_id": "8421"},
        {"$set": {"enrol_until": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    ok, reply = _auth(_hello("8421", SHARED))
    assert ok and "device_key" not in reply, "shared key can still claim a board's key"


def test_pairing_opens_the_window_but_never_reissues_a_confirmed_key(db):
    ok, reply = _auth(_hello("8421", SHARED))
    own = bytes.fromhex(reply["device_key"])
    _auth(_hello("8421", own, kv=2))
    from app.features.device_keys import get_key, open_enrolment
    open_enrolment("8421")
    assert get_key("8421")["state"] == "confirmed"
    ok, reply = _auth(_hello("8421", SHARED))
    assert not ok, "re-pairing let the shared key back in"
