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


def test_each_board_has_its_own_line_of_releases(db):
    """A camera release never reaches the brain, and the brain's keys never move.

    Robots already in the field ask without a board and must keep finding the
    brain's releases exactly where they were.
    """
    fs.publish("1.0.0", b"brain", "ab", rollout=100)
    fs.publish("0.5.0", b"camera", "cd", rollout=100, board="cam")
    fs.publish("0.5.0", b"room", "ef", rollout=100, board="room")

    assert fs.manifest_for("x", "0.9")["version"] == "1.0.0"
    assert fs.manifest_for("x", "0.4.0", "cam")["signature"] == "cd"
    assert fs.manifest_for("x", "0.4.0", "room")["signature"] == "ef"
    assert b"".join(fs.image_chunks("0.5.0", "cam")) == b"camera"
    assert b"".join(fs.image_chunks("0.5.0", "room")) == b"room"
    assert fs.image_chunks("0.5.0") is None               # no brain 0.5.0
    assert db["sandy_firmware"].find_one({"_id": "1.0.0"}) is not None
    # A camera version does not block a brain version and the other way round.
    assert fs.publish("0.6.0", b"brain", "ab")["error"] == "not_newer"
    assert fs.publish("0.6.0", b"camera", "cd", board="cam")["ok"]
    assert fs.publish("1.0.0", b"x", "ab", board="nope")["error"] == "bad_board"


def test_a_board_image_must_fit_its_own_slot(db):
    room_slot = fs.BOARD_SLOT_BYTES["room"]
    assert fs.publish("1.0.0", b"x" * (room_slot + 1), "ab", board="room")["error"] == "bad_size"
    assert fs.publish("1.0.0", b"x" * (room_slot + 1), "ab", board="cam")["ok"]


def test_the_small_boards_get_their_board_in_the_url(db, monkeypatch):
    from app import config
    from app.api.server import create_app
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setattr(config, "SANDY_FIRMWARE_TOKEN", "t0k", raising=False)
    c = create_app(mongo_db=db, semantic_memory_stats_fn=lambda: {}).test_client()
    data = {"version": "0.5.0", "signature": "ab", "board": "room", "rollout": "100",
            "image": (io.BytesIO(b"roomimg"), "fw.bin")}
    r = c.post("/api/firmware/publish", data=data, content_type="multipart/form-data",
               headers={"Authorization": "Bearer t0k"})
    assert r.status_code == 200, r.get_json()
    assert c.get("/api/firmware/manifest?device_id=a&v=0.4.0").status_code == 204
    m = c.get("/api/firmware/manifest?board=room&device_id=a&v=0.4.0").get_json()
    assert m["url"] == "/api/firmware/image/0.5.0?board=room"
    img = c.get(m["url"])
    assert img.data == b"roomimg" and img.headers["Content-Length"] == "7"
    assert c.get("/api/firmware/manifest?board=evil").status_code == 400


def test_both_small_boards_carry_the_same_updater_and_the_real_key():
    """One updater, two copies — Arduino sketches cannot share a file.

    They must not drift, and the public key in them must be the one the publish
    script signs against, or every update is refused in the field.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    cam = (root / "vision-core" / "sandy_ota_pull.h").read_text()
    room = (root / "room-node" / "sandy_ota_pull.h").read_text()
    assert cam == room, "vision-core and room-node have different sandy_ota_pull.h"
    pem = (root / "firmware" / "brain-core" / "main" / "fw_pubkey.pem").read_text()
    body = [ln for ln in pem.splitlines() if ln and "-----" not in ln]
    for line in body:
        assert f'"{line}\\n"' in cam, "the updater's public key is not fw_pubkey.pem"
    assert '"sandy-fw|%s|%s|%ld|%s"' in cam, "the board is not in the signed message"
    assert 'extern "C" bool verifyRollbackLater()' in cam


def test_both_small_boards_keep_their_identity_out_of_the_image():
    """One update image goes to every robot and is downloadable by anyone.

    So the pairing code, the broker login and the Wi-Fi cannot live in it: they
    live in the board's NVS, written by the first cable flash, and an image built
    with the example values leaves them alone.
    """
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    cam = (root / "vision-core" / "sandy_identity.h").read_text()
    assert cam == (root / "room-node" / "sandy_identity.h").read_text()
    assert 'strncmp(v, "YOUR_", 5) == 0' in cam and '"XXXX"' in cam
    for sketch in ("vision-core/vision-core.ino", "room-node/room-node.ino"):
        src = (root / sketch).read_text()
        assert "sandyIdentityLoad(SANDY_PAIR_CODE, SANDY_MQTT_HOST" in src, sketch
        assert "sandyOtaBegin(ota)" in src and "sandyOtaLoop(" in src, sketch
    # Nothing reads the compiled identity directly any more.
    for f in list((root / "vision-core").glob("cam_*.ino")) + [root / "room-node" / "room-node.ino"]:
        code = "\n".join(ln for ln in f.read_text().splitlines()
                         if not ln.lstrip().startswith("//") and "sandyIdentityLoad" not in ln
                         and "SANDY_MQTT_USER, SANDY_MQTT_PASS" not in ln)
        for name in ("SANDY_MQTT_USER", "SANDY_MQTT_PASS", "SECRET_SSID"):
            assert name not in code, f"{f.name} still reads {name} from the image"


def test_the_publisher_refuses_an_image_that_carries_a_secret(tmp_path):
    import importlib.util
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location("pf", root / "scripts" / "publish_firmware.py")
    pf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pf)
    (tmp_path / "secrets.h").write_text(
        'const char* WIFI_SSID = "HomeNet123";\n'
        '#define SANDY_MQTT_HOST "abc.s1.eu.hivemq.cloud"\n'
        '#define SANDY_PAIR_CODE "SANDY-8421"\n'
        '#define SANDY_UPLOAD_HOST "x.herokuapp.com"\n'
        '#define OTA_HOSTNAME "sandy-room"\n'
        '#define SANDY_WS_HMAC_KEY "YOUR_SHARED_UPLOAD_KEY"\n')
    found = set(pf._secret_values(tmp_path))
    assert found == {b"HomeNet123", b"abc.s1.eu.hivemq.cloud", b"SANDY-8421"}
    assert set(pf.SMALL_BOARDS) == {"cam", "room"}
    assert pf.SMALL_BOARDS["room"]["slot"] == fs.BOARD_SLOT_BYTES["room"]
    assert pf.SMALL_BOARDS["cam"]["slot"] == fs.BOARD_SLOT_BYTES["cam"]


def test_the_partition_tables_match_the_server_slots():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for sketch, board in (("vision-core", "cam"), ("room-node", "room")):
        rows = [ln.split(",") for ln in (root / sketch / "partitions.csv").read_text().splitlines()
                if ln.strip() and not ln.startswith("#")]
        apps = [r for r in rows if r[1].strip() == "app"]
        assert [r[2].strip() for r in apps] == ["ota_0", "ota_1"], sketch
        for r in apps:
            assert int(r[4], 16) == fs.BOARD_SLOT_BYTES[board], sketch
        assert rows[0][0].strip() == "nvs" and rows[0][3].strip() == "0x9000", (
            f"{sketch}: moving NVS would wipe the saved identity and Wi-Fi")
