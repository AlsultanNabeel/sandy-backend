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
        device_keys.confirm_key(kid)
        assert node_store._wipe_board("node3")
        cam = [p for t, p in sent if t == "sandy/node/node3/cam/factory_reset"]
        assert len(cam) == 1
        assert _check(cam[0], "node3:cam", bytes.fromhex(cam_key))
        brain = [p for t, p in sent if t == "sandy/node/node3/factory_reset"]
        assert brain and not _check(brain[0], "node3:cam", bytes.fromhex(cam_key))
    finally:
        appdb.reset()


# ── F6: a key only issued may not be on the board yet ──

def _released(monkeypatch, confirm: bool):
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
        device_keys.open_enrolment("node4")
        own = device_keys.issue_key("node4")
        if confirm:
            device_keys.confirm_key("node4")
        assert node_store._wipe_board("node4")
    finally:
        appdb.reset()
    return [p for t, p in sent if t == "sandy/node/node4/factory_reset"], bytes.fromhex(own)


def test_an_erase_under_an_unconfirmed_key_goes_with_both_keys(monkeypatch):
    brain, own = _released(monkeypatch, confirm=False)
    assert len(brain) == 2
    assert any(_check(c, "node4", own) for c in brain)
    assert any(_check(c, "node4", b"shared-secret") for c in brain)


def test_a_confirmed_key_alone_signs_it(monkeypatch):
    brain, own = _released(monkeypatch, confirm=True)
    assert len(brain) == 1 and _check(brain[0], "node4", own)
