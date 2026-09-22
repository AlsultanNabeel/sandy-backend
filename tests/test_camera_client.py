"""Camera client tests — asking for a photo, and hearing why it is not coming.

The photo itself arrives over signed HTTPS (devices_api /api/cam/upload). What
lives here is the other half: the command that asks for it, and the camera's
own failure report becoming the answer the app reads — instead of forty seconds
of polling and "no photo" for every possible cause.
"""

import json
import os

import mongomock
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-camera")

from app.integrations import camera_client  # noqa: E402

NODE = "sandybrain01"


@pytest.fixture()
def db():
    import app.db as appdb

    database = mongomock.MongoClient()["t"]
    appdb.configure(database)
    try:
        yield database
    finally:
        appdb.reset()


def _capture_sent(monkeypatch):
    sent = []

    def fake_send(node_id, command):
        sent.append((node_id, command))
        return True

    monkeypatch.setattr(camera_client, "_send", fake_send)
    return sent


def test_snapshot_command_shape(monkeypatch):
    sent = _capture_sent(monkeypatch)
    req = camera_client.start_snapshot(NODE, settle_ms=99999, flash="weird")
    assert req and sent
    node, cmd = sent[0]
    assert node == NODE
    assert cmd["cmd"] == "snapshot" and cmd["id"] == req
    assert cmd["settle_ms"] == 3000, "settle is not clamped"
    assert cmd["flash"] == "auto", "an unknown flash mode reached the board"


def test_an_undelivered_command_fails_fast(monkeypatch):
    monkeypatch.setattr(camera_client, "_send", lambda n, c: False)
    assert camera_client.start_snapshot(NODE) is None


def test_the_camera_saying_no_becomes_the_answer(db):
    camera_client.on_event(NODE, json.dumps({"id": "abc123", "error": "upload_failed"}))
    err = camera_client.fetch_snapshot_error(NODE, "abc123")
    assert err and err["error"] == "upload_failed"
    assert err["message"], "the person holding the phone gets no words"
    assert camera_client.fetch_snapshot(NODE, "abc123") is None


def test_a_photo_that_did_arrive_beats_a_late_error(db):
    camera_client.store_snapshot(NODE, "p1", b"\xff\xd8" + b"x" * 200)
    camera_client.on_event(NODE, json.dumps({"id": "p1", "error": "capture_failed"}))
    assert camera_client.fetch_snapshot(NODE, "p1")
    assert camera_client.fetch_snapshot_error(NODE, "p1") is None


def test_events_that_are_not_errors_change_nothing(db):
    for payload in ("not json", "[]", json.dumps({"id": "q", "event": "uploaded"}),
                    json.dumps({"error": "capture_failed"}),
                    json.dumps({"id": "x" * 80, "error": "capture_failed"})):
        camera_client.on_event(NODE, payload)
    assert camera_client.fetch_snapshot_error(NODE, "q") is None


def test_there_is_no_photo_over_the_broker_path():
    assert not hasattr(camera_client, "on_chunk"), (
        "photo pieces over the broker are back — unsigned, through a third "
        "party, and silently lossy")
