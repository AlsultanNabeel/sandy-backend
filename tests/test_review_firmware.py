"""Firmware releases: signed metadata, staged rollout, publish guard."""
import hashlib
import io

import mongomock
import pytest

from app import db as appdb
from app.features import firmware_store as fs


@pytest.fixture
def db():
    d = mongomock.MongoClient().db
    appdb.configure(d)
    yield d
    appdb.reset()


def test_publish_and_manifest_by_rollout(db):
    img = b"\xe9" + b"x" * 1_500_000
    r = fs.publish("0.9.2", img, "ab" * 70, rollout=0, canary=["8421"])
    assert r["ok"] and r["sha256"] == hashlib.sha256(img).hexdigest()

    assert fs.manifest_for("8421", "0.9.1")["version"] == "0.9.2"   # canary
    assert fs.manifest_for("8421", "0.9.2") is None                 # up to date
    others = [f"dev{i}" for i in range(200)]
    assert all(fs.manifest_for(d, "0.9.1") is None for d in others)  # 0 %

    fs.set_rollout("0.9.2", 100)
    assert all(fs.manifest_for(d, "0.9.1") for d in others)
    assert b"".join(fs.image_chunks("0.9.2")) == img                 # multi-chunk


def test_no_downgrade_or_same_version(db):
    fs.publish("0.10.0", b"a" * 10, "ab", rollout=100)
    assert fs.publish("0.9.9", b"b" * 10, "ab")["error"] == "not_newer"
    assert fs.publish("0.10.0", b"b" * 10, "ab")["error"] == "not_newer"
    assert fs.version_key("0.10.0") > fs.version_key("0.9.9")


def test_bucket_is_stable():
    assert fs.bucket("8421") == fs.bucket("8421")
    assert 0 <= fs.bucket("x") < 100


def test_publish_endpoint_needs_the_token(db, monkeypatch):
    from app import config
    from app.api.server import create_app
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setattr(config, "SANDY_FIRMWARE_TOKEN", "t0k", raising=False)
    c = create_app(mongo_db=db, semantic_memory_stats_fn=lambda: {}).test_client()
    data = {"version": "1.0.0", "signature": "ab",
            "image": (io.BytesIO(b"img"), "fw.bin")}
    assert c.post("/api/firmware/publish", data=data,
                  content_type="multipart/form-data").status_code == 401
    data["image"] = (io.BytesIO(b"img"), "fw.bin")
    r = c.post("/api/firmware/publish", data=data, content_type="multipart/form-data",
               headers={"Authorization": "Bearer t0k"})
    assert r.status_code == 200, r.get_json()
    assert c.get("/api/firmware/manifest?device_id=a&v=0.9").status_code == 204
    c.post("/api/firmware/rollout", json={"version": "1.0.0", "rollout": 100},
           headers={"Authorization": "Bearer t0k"})
    m = c.get("/api/firmware/manifest?device_id=a&v=0.9").get_json()
    assert m["url"] == "/api/firmware/image/1.0.0"
    assert c.get(m["url"]).data == b"img"
