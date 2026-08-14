"""Camera client tests — chunk reassembly without a camera, a broker, or a robot.

The camera is a request that expects an answer, which no other control is: the
board splits a JPEG across many MQTT messages and something has to hold the pieces
while a different thread waits. Everything that can go wrong there goes wrong
quietly — a lost chunk, a late chunk, an answer nobody asked for, a stream that
never ends — so each one has a test.
"""

import base64
import json
import os
import threading

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-camera")

from app.integrations import camera_client  # noqa: E402

NODE = "sandybrain01"


@pytest.fixture(autouse=True)
def clean_state():
    camera_client._pending.clear()
    yield
    camera_client._pending.clear()


def chunk(req_id, seq, total, blob):
    return json.dumps({
        "id": req_id, "seq": seq, "total": total,
        "data": base64.b64encode(blob).decode(),
    })


def _capture_sent(monkeypatch):
    """Stand in for the broker; hand back whatever the client tried to publish."""
    sent = []

    def fake_send(node_id, command):
        sent.append((node_id, command))
        return True

    monkeypatch.setattr(camera_client, "_send", fake_send)
    return sent


def test_chunks_reassemble_in_order_regardless_of_arrival(monkeypatch):
    sent = _capture_sent(monkeypatch)
    image = b"\xff\xd8" + b"PHOTO-BYTES" * 20 + b"\xff\xd9"
    parts = [image[i:i + 20] for i in range(0, len(image), 20)]

    result = {}

    def ask():
        result["data"] = camera_client.request_snapshot(NODE, timeout_s=5)

    t = threading.Thread(target=ask)
    t.start()
    while not sent:
        pass
    req_id = sent[0][1]["id"]

    # Out of order on purpose — MQTT gives no ordering guarantee across messages.
    for seq in (2, 0, 3, 1)[:len(parts)]:
        if seq < len(parts):
            camera_client.on_chunk(NODE, chunk(req_id, seq, len(parts), parts[seq]))
    for seq in range(len(parts)):
        camera_client.on_chunk(NODE, chunk(req_id, seq, len(parts), parts[seq]))

    t.join(timeout=6)
    assert result["data"] == image


def test_a_missing_chunk_times_out_instead_of_returning_a_broken_image(monkeypatch):
    sent = _capture_sent(monkeypatch)
    result = {}

    def ask():
        result["data"] = camera_client.request_snapshot(NODE, timeout_s=0.4)

    t = threading.Thread(target=ask)
    t.start()
    while not sent:
        pass
    req_id = sent[0][1]["id"]
    camera_client.on_chunk(NODE, chunk(req_id, 0, 3, b"aaa"))
    camera_client.on_chunk(NODE, chunk(req_id, 2, 3, b"ccc"))   # seq 1 never comes

    t.join(timeout=3)
    # Half a photo is not a photo. Returning the bytes we happen to have would
    # hand the caller a corrupt JPEG and call it success.
    assert result["data"] is None


def test_chunks_nobody_is_waiting_for_are_dropped():
    # A late chunk from a timed-out request, or a board talking to a backend that
    # never asked. Buffering these is how a memory leak starts.
    camera_client.on_chunk(NODE, chunk("ghost-request", 0, 1, b"x"))
    assert camera_client._pending == {}


def test_a_malformed_chunk_cannot_raise():
    camera_client.on_chunk(NODE, "not json at all")
    camera_client.on_chunk(NODE, json.dumps({"id": "x"}))          # no data
    camera_client.on_chunk(NODE, json.dumps({"seq": 0, "data": "!!"}))  # no id
    assert camera_client._pending == {}


def test_an_oversized_stream_is_abandoned(monkeypatch):
    sent = _capture_sent(monkeypatch)
    monkeypatch.setattr(camera_client, "_MAX_IMAGE_BYTES", 100)
    result = {}

    def ask():
        result["data"] = camera_client.request_snapshot(NODE, timeout_s=5)

    t = threading.Thread(target=ask)
    t.start()
    while not sent:
        pass
    req_id = sent[0][1]["id"]
    # Claims 50 chunks, each bigger than the whole cap.
    for seq in range(3):
        camera_client.on_chunk(NODE, chunk(req_id, seq, 50, b"z" * 60))

    t.join(timeout=6)
    assert result["data"] is None


def test_an_undelivered_command_fails_fast(monkeypatch):
    # send_to_topic refuses when the caller does not own the node. Waiting the
    # full timeout for an answer we know will never come is just a slow no.
    monkeypatch.setattr(camera_client, "_send", lambda n, c: False)
    assert camera_client.request_snapshot(NODE, timeout_s=30) is None
    assert camera_client._pending == {}


def test_snapshot_command_shape(monkeypatch):
    sent = _capture_sent(monkeypatch)
    threading.Thread(target=lambda: camera_client.request_snapshot(
        NODE, timeout_s=0.2, settle_ms=9999, flash="nonsense")).start()
    while not sent:
        pass
    node_id, cmd = sent[0]
    assert node_id == NODE
    assert cmd["cmd"] == "snapshot"
    assert cmd["settle_ms"] == 3000        # clamped, not passed through
    assert cmd["flash"] == "auto"          # unknown value falls back, never sent raw
