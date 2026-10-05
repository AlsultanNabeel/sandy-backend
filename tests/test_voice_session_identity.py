"""Who a voice session speaks for is decided by its own handshake, never left over.

The handshake runs on a server thread that is reused between connections, and the
identity lives in a context variable on that thread. A board nobody paired yet
(its owner is still setting it up) must start with no one's memory, not the last
caller's.
"""
import hashlib
import hmac
import json
import time

import mongomock
import pytest

from app import db as appdb
from app.api.voice_ws import session as sess
from app.api.voice_ws.memory import get_voice_channel, get_voice_identity

SHARED = b"shared-test-key"


class _WS:
    def __init__(self, hello):
        self._hello = json.dumps(hello)
        self.sent = []

    def receive(self, timeout=None):
        return self._hello

    def send(self, data):
        self.sent.append(json.loads(data) if data.startswith("{") else data)


def _hello(device_id, key=SHARED):
    ts = int(time.time() * 1000)
    return {"type": "hello", "device_id": device_id, "ts": ts,
            "hmac": hmac.new(key, f"{device_id}{ts}".encode(), hashlib.sha256).hexdigest()}


@pytest.fixture
def db(monkeypatch):
    d = mongomock.MongoClient().db
    appdb.configure(d)
    monkeypatch.setattr(sess, "_HMAC_KEY", SHARED)
    d["sandy_nodes"].insert_one({"node_id": "8421", "user_id": "owner-1"})
    yield d
    appdb.reset()


def test_an_unpaired_board_does_not_inherit_the_last_caller(db):
    assert sess._authenticate(_WS(_hello("8421")), "t")
    assert get_voice_identity() == "owner-1"

    # Same thread, next connection: a board its owner has not paired yet.
    assert sess._authenticate(_WS(_hello("9999")), "t")
    assert get_voice_identity() == "", "an unpaired robot spoke as the previous customer"


def test_a_refused_handshake_leaves_no_identity_behind(db):
    assert sess._authenticate(_WS(_hello("8421")), "t")
    bad = _hello("9999")
    bad["hmac"] = "00"
    assert not sess._authenticate(_WS(bad), "t")
    assert get_voice_identity() == ""
    assert get_voice_channel() == "الصوت"
