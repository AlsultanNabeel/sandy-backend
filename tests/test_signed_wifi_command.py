"""The Wi-Fi command is signed like the erase, with its password sealed under the board's key.

Anyone allowed to publish on a robot's topics could move it onto their own network, and
read its owner's password off the broker. The board checks the signature, the time and
that it has not seen the command before, and only then opens the password.
"""
from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import patch

import mongomock

import app.db as appdb
from app.features import device_keys, wifi_switch


def _open(command: str, signer: str, key: bytes):
    """What the board does (sandy_mqtt.c::_handle_wifi): check, then open."""
    tag, ms, ssid_hex, sealed_hex, mac = command.split(":")
    assert tag == "wifi"
    want = hmac.new(key, f"wifi|{signer}|{ms}|{ssid_hex}|{sealed_hex}".encode(),
                    hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, mac):
        return None
    stream = b"".join(hmac.new(key, f"wifi-pass|{signer}|{ms}|{i}".encode(),
                               hashlib.sha256).digest() for i in range(2))
    plain = bytes(a ^ b for a, b in zip(bytes.fromhex(sealed_hex), stream))
    assert abs(time.time() * 1000 - int(ms)) < 60_000
    return bytes.fromhex(ssid_hex).decode(), plain.split(b"\0")[0].decode()


def _sent_payloads(node):
    with patch("app.features.node_store.get_node", return_value=node), \
         patch("app.integrations.device_publisher.get_device_publisher") as c:
        c.return_value.publish_service.return_value = True
        res = wifi_switch.switch_network(node["node_id"], "بيت: 5G", "hunter2:22")
    assert res["ok"] is True
    return [call[0] for call in c.return_value.publish_service.call_args_list]


def test_signed_and_sealed_with_the_boards_own_key(monkeypatch):
    monkeypatch.setattr("app.api.voice_ws._config._HMAC_KEY", b"shared-secret")
    appdb.configure(mongomock.MongoClient()["t"])
    try:
        device_keys.open_enrolment("n1")
        own = bytes.fromhex(device_keys.issue_key("n1"))
        device_keys.confirm_key("n1")
        sent = _sent_payloads({"node_id": "n1", "firmware_version": "0.12.0"})
        assert len(sent) == 1
        topic, payload = sent[0]
        assert topic == "sandy/node/n1/wifi"
        assert "hunter2" not in payload and "5G" not in payload
        assert _open(payload, "n1", own) == ("بيت: 5G", "hunter2:22")
        assert _open(payload, "n1", b"shared-secret") is None
    finally:
        appdb.reset()


def test_a_key_only_issued_sends_it_under_both_keys_and_a_new_board_the_shared_one(monkeypatch):
    monkeypatch.setattr("app.api.voice_ws._config._HMAC_KEY", b"shared-secret")
    appdb.configure(mongomock.MongoClient()["t"])
    try:
        sent = _sent_payloads({"node_id": "n2", "firmware_version": "0.12.0"})
        assert [_open(p, "n2", b"shared-secret") for _, p in sent] == [("بيت: 5G", "hunter2:22")]

        device_keys.open_enrolment("n3")
        own = bytes.fromhex(device_keys.issue_key("n3"))
        sent = _sent_payloads({"node_id": "n3", "firmware_version": "0.12.0"})
        opened = [(_open(p, "n3", own), _open(p, "n3", b"shared-secret")) for _, p in sent]
        assert len(sent) == 2 and any(o[0] for o in opened) and any(o[1] for o in opened)
    finally:
        appdb.reset()


def test_a_board_on_older_firmware_still_gets_the_old_form_until_it_updates(monkeypatch):
    """Boards in the field must keep working: they read only "<ssid>\\n<password>"."""
    monkeypatch.setattr("app.api.voice_ws._config._HMAC_KEY", b"shared-secret")
    appdb.configure(mongomock.MongoClient()["t"])
    try:
        (_, brain), = _sent_payloads({"node_id": "n5", "firmware_version": "0.11.6"})
        assert brain == "بيت: 5G\nhunter2:22"
    finally:
        appdb.reset()
