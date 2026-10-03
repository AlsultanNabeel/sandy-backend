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
