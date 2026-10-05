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


_NEUTRAL = "الافتراضي: عاملي أي حدا"


@pytest.fixture
def voiceprint_owner(db, monkeypatch):
    """u1 taught the robot their voice; the instruction cache is cold."""
    import app.api.voice_ws.tools as vt
    from app.features import speaker_id

    monkeypatch.setenv("SANDY_REQUIRE_SPEAKER_AUTH", "0")
    monkeypatch.setattr(speaker_id, "has_profile", lambda uid: uid == "u1")
    monkeypatch.setattr("app.brain.persona.build_effective_persona", lambda _uid: "شخصية")
    vt.clear_instruction_cache()
    yield vt
    vt.clear_instruction_cache()


def test_the_app_call_is_not_handed_the_robot_s_guarded_instruction(voiceprint_owner):
    """Built on a pool thread, where the session's channel never arrives."""
    from app.api.voice_ws.memory import set_voice_channel
    from app.api.voice_ws.session import _APP_CHANNEL, _ROBOT_CHANNEL

    vt = voiceprint_owner
    set_voice_channel("")                     # what a pool thread has
    app_text = vt._build_cached_instruction("u1", _APP_CHANNEL)
    assert _NEUTRAL not in app_text, "the owner's own phone call got the stranger persona"

    robot_text = vt._build_cached_instruction("u1", _ROBOT_CHANNEL)
    assert _NEUTRAL in robot_text, "the robot was served the app's trusting instruction"
    assert _NEUTRAL not in vt._build_cached_instruction("u1", _APP_CHANNEL)

