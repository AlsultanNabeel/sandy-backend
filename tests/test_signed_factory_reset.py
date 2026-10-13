"""A factory reset is signed: a bare word on the broker no longer wipes a robot."""
from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path

import mongomock

import app.db as appdb
from app.features import device_keys, node_store

FW = Path(__file__).resolve().parent.parent / "firmware/brain-core/main/sandy_mqtt.c"


def _check(command: str, node_id: str, key: bytes) -> bool:
    _, ms, mac = command.split(":")
    want = hmac.new(key, f"factory_reset|{node_id}|{ms}".encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, mac) and abs(time.time() * 1000 - int(ms)) < 60_000


def test_signed_with_the_boards_own_key_once_it_has_one(monkeypatch):
    appdb.configure(mongomock.MongoClient()["t"])
    try:
        device_keys.open_enrolment("node1")
        own = device_keys.issue_key("node1")
        command = node_store._erase_command("node1")
        assert command.startswith("erase:")
        assert _check(command, "node1", bytes.fromhex(own))
    finally:
        appdb.reset()


def test_signed_with_the_shared_key_before_that(monkeypatch):
    monkeypatch.setattr("app.api.voice_ws._config._HMAC_KEY", b"shared-secret")
    appdb.configure(mongomock.MongoClient()["t"])
    try:
        command = node_store._erase_command("node2")
        assert _check(command, "node2", b"shared-secret")
    finally:
        appdb.reset()


def test_the_board_takes_only_a_signed_recent_command():
    src = FW.read_text(encoding="utf-8")
    body = src[src.index("static void _handle_factory_reset("):]
    body = body[:body.index("\n}\n")]
    assert "voice_verify_signed(" in body and "ERASE_WINDOW_MS" in body
    assert 'factory_reset|%s|%s' in body
    assert '!strcmp(val, "erase")' not in src


# ── F3: the camera has its own signed erase ──

CAM = Path(__file__).resolve().parent.parent / "firmware/vision-core"


def test_a_release_sends_the_camera_its_own_erase_signed_with_its_own_key(monkeypatch):
    sent = []

    class _Client:
        def publish_service(self, topic, payload):
            sent.append((topic, payload))
            return True

    monkeypatch.setattr("app.integrations.room_device.get_room_device_client",
                        lambda: _Client())
    monkeypatch.setattr("app.api.voice_ws._config._HMAC_KEY", b"shared-secret")
    appdb.configure(mongomock.MongoClient()["t"])
    try:
        kid = device_keys.cam_key_id("node3")
        device_keys.open_enrolment(kid)
        cam_key = device_keys.issue_key(kid)
        assert node_store._wipe_board("node3")
        cam = [p for t, p in sent if t == "sandy/node/node3/cam/factory_reset"]
        assert len(cam) == 1
        assert _check(cam[0], "node3:cam", bytes.fromhex(cam_key))
        brain = [p for t, p in sent if t == "sandy/node/node3/factory_reset"]
        assert brain and not _check(brain[0], "node3:cam", bytes.fromhex(cam_key))
    finally:
        appdb.reset()


def _cam_src() -> str:
    return (CAM / "cam_wifi.ino").read_text(encoding="utf-8")


def _fn(src: str, sig: str) -> str:
    start = src.index(sig)
    i = src.index("{", start)
    depth = 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[i:j + 1]
    raise AssertionError(sig)


def test_the_camera_erase_forgets_the_network_and_settings_and_keeps_its_identity_and_key():
    forget = _fn(_cam_src(), "static void camForgetNetworkAndSettings(")
    # The network, by name: the saved one and the first one in the identity namespace.
    for name in ("WIFI_K_SSID", "WIFI_K_PASS", "WIFI_K_TRYING", '"ws"', '"wp"'):
        assert f"p.remove({name})" in forget, name
    assert "settingsClear();" in forget                  # the settings namespace alone
    # Never the whole store, the identity's other fields or the camera's own key.
    for never in ("nvs_flash_erase", "clear()", "sandy_ckey", '"pair"', '"mh"', '"mu"',
                  '"mp"', '"sk"', "ownKeyDrop"):
        assert never not in forget, never
    settings_clear = _fn((CAM / "cam_control.ino").read_text(encoding="utf-8"),
                         "static void settingsClear(")
    assert "g_prefs.clear();" in settings_clear
    assert 'begin(SETTINGS_NVS_NAMESPACE' in (CAM / "cam_control.ino").read_text(encoding="utf-8")
    assert '#define SETTINGS_NVS_NAMESPACE    "sandycam"' in (CAM / "config.h").read_text(
        encoding="utf-8")


def test_the_camera_takes_only_a_signed_recent_erase():
    src = _cam_src()
    signed = _fn(src, "static bool camEraseSigned(")
    assert '"factory_reset|") + camNodeId() + ":cam|" + ms' in signed
    assert "CAM_CLOCK_SANE_EPOCH" in signed and "CAM_ERASE_WINDOW_MS" in signed
    handler = _fn(src, "void handleCamFactoryReset(")
    assert handler.index("camEraseSigned(value)") < handler.index("camForgetNetworkAndSettings()")
    mqtt = (CAM / "cam_mqtt.ino").read_text(encoding="utf-8")
    assert "handleCamFactoryReset(value)" in mqtt and "g_topicErase.c_str()" in mqtt
