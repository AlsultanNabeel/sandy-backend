"""The camera enrols its own upload key, separate from the robot's."""
import hashlib
import hmac
import time

import mongomock
import pytest
from flask import Flask

from app import db as appdb
from app.api import devices_api
from app.api.voice_ws import _config as vcfg
from app.features import device_keys as dk

SHARED = b"shared-test-key"
JPEG = b"\xff\xd8" + b"x" * 200


@pytest.fixture
def client(monkeypatch):
    d = mongomock.MongoClient().db
    appdb.configure(d)
    monkeypatch.setattr(vcfg, "_HMAC_KEY", SHARED)
    import app.integrations.camera_client as cc
    monkeypatch.setattr(cc, "store_snapshot", lambda *a, **k: None)
    d["sandy_nodes"].insert_one({"node_id": "8421", "user_id": "owner-1"})
    dk.open_enrolment(dk.cam_key_id("8421"))
    app = Flask(__name__)
    devices_api.register_devices_api(app, d)
    yield app.test_client(), d
    appdb.reset()


def _post(c, key, kv=None, node="8421"):
    ts = str(int(time.time() * 1000))
    sig = hmac.new(key, f"{node}live{ts}".encode(), hashlib.sha256).hexdigest()
    h = {"X-Sandy-Node": node, "X-Sandy-Req": "live", "X-Sandy-Ts": ts,
         "X-Sandy-Sig": sig, "Content-Type": "image/jpeg"}
    if kv:
        h["X-Sandy-Kv"] = str(kv)
    return c.post("/api/cam/upload", data=JPEG, headers=h)


def test_camera_enrols_then_only_its_own_key_works(client):
    c, _ = client
    r = _post(c, SHARED)
    assert r.status_code == 200
    own = bytes.fromhex(r.get_json()["device_key"])
    assert dk.get_key("8421") is None, "the camera took the robot's key record"

    r = _post(c, own, kv=2)
    assert r.status_code == 200 and "device_key" not in r.get_json()
    r = _post(c, SHARED)
    assert r.status_code == 401, "shared key still uploads as this camera"


def test_unknown_own_key_tells_the_camera_to_drop_it(client):
    c, _ = client
    r = _post(c, b"k" * 32, kv=2)
    assert r.status_code == 401 and r.get_json()["error"] == "key_unknown"


def test_no_camera_key_outside_the_pairing_window(client):
    c, d = client
    d["sandy_device_keys"].delete_many({})
    r = _post(c, SHARED)
    assert r.status_code == 200 and "device_key" not in r.get_json()


def _post_v2(c, key, body=JPEG, node="8421", req="live", ts=None, tamper=None):
    """The current firmware: the body's hash is inside the signature."""
    ts = ts or str(int(time.time() * 1000))
    digest = hashlib.sha256(body).hexdigest()
    sig = hmac.new(key, f"{node}{req}{ts}{digest}".encode(), hashlib.sha256).hexdigest()
    h = {"X-Sandy-Node": node, "X-Sandy-Req": req, "X-Sandy-Ts": ts,
         "X-Sandy-Sig": sig, "X-Sandy-Body-Sha256": digest,
         "Content-Type": "image/jpeg"}
    return c.post("/api/cam/upload", data=tamper or body, headers=h)


def test_the_signature_covers_the_picture(client):
    """Swap the image on the way and keep the signature: refused."""
    c, _ = client
    assert _post_v2(c, SHARED).status_code == 200
    forged = b"\xff\xd8" + b"y" * 200
    r = _post_v2(c, SHARED, tamper=forged)
    assert r.status_code == 401, "a replaced picture passed with the old signature"


def test_the_same_upload_twice_is_a_replay(client):
    c, _ = client
    ts = str(int(time.time() * 1000))
    assert _post_v2(c, SHARED, ts=ts).status_code == 200
    r = _post_v2(c, SHARED, ts=ts)
    assert r.status_code == 401 and r.get_json()["error"] == "replay"


def test_ids_and_size_are_checked_before_anything_else(client):
    c, _ = client
    assert _post_v2(c, SHARED, req="a\"b;x").status_code == 400
    assert _post_v2(c, SHARED, node="../etc").status_code == 400
    huge = b"\xff\xd8" + b"z" * (600 * 1024)
    assert _post_v2(c, SHARED, body=huge).status_code == 413
