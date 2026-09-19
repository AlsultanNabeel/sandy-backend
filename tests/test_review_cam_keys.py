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
