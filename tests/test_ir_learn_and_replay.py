"""Infrared — the board half of a feature the backend already had.

A receiver and an LED that cost about a dollar and a half turn every remote in
the room into something she can press: the television, the air conditioner, the
fan. No relays, no wiring into the mains, no second board. The learn topic, the
endpoint and the `ir` device type had been sitting complete for a while with
nothing on the board to answer them.

One output, `ir`, two payloads: `learn` arms the receiver, anything else is a
recorded code to replay. That shape is the backend's, not a new one — a button
on an `ir` device already carries its code as the payload.
"""

from __future__ import annotations

import os
from pathlib import Path

import mongomock
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-ir")

from app.features import device_store, node_store  # noqa: E402
from app.utils.user_profiles import active_user_profile_context  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def as_tenant(tenant_id):
    return active_user_profile_context(
        {"chat_id": tenant_id, "permissions": "all", "relation": "user"}
    )


@pytest.fixture()
def db():
    database = mongomock.MongoClient().db
    device_store.init_device_store(database)
    node_store.init_node_store(database)
    return database


# ── the round trip ───────────────────────────────────────────────────────────

def test_a_learned_button_becomes_the_payload_the_board_replays(db):
    """Learn stores a code under a name; pressing sends that code back out.

    The device carries the code, so the board needs no memory of its own and a
    second robot in the same house learns nothing it was not taught.
    """
    with as_tenant("tenant-a"):
        node_store.pair_node("8421", label="ساندي")
        node_store.ingest_status("8421", outputs=[{"id": "ir", "kind": "ir"}])

        dev = device_store.get_device("sandy_ir")
        assert dev is not None, "the board declared ir and no device appeared"
        assert dev["control_type"] == "ir"
        assert device_store.device_topic(dev) == "sandy/node/8421/ir"

        # Nothing learned yet: a press is refused rather than guessed.
        refused = device_store.command_payload(dev, "fan_on")
        assert refused["ok"] is False and refused["error"] == "not_learned"

        code = "9000,4500,560,560,560,1690,560"
        assert device_store.learn_ir_button("sandy_ir", "fan_on", code)["ok"]

        dev = device_store.get_device("sandy_ir")
        sent = device_store.command_payload(dev, "fan_on")
        assert sent["ok"] is True
        assert sent["payload"] == code, "the replayed code is not the learned one"


def test_heartbeats_never_erase_learned_buttons(db):
    """The catalogue must not carry `meta` for the IR device.

    `_refresh_from_catalogue` merges the catalogue's meta over the device's on
    every heartbeat. A `"meta": {"buttons": {}}` row — even empty — would wipe
    every button the owner taught, every five seconds, for ever. An absent meta
    is the only way to say "this field belongs to the owner, not to me".
    """
    from app.features.node_provision import PART_CATALOGUE

    assert "meta" not in PART_CATALOGUE["ir"], (
        "the IR catalogue row carries meta and will overwrite learned buttons")

    with as_tenant("tenant-a"):
        node_store.pair_node("8421", label="ساندي")
        node_store.ingest_status("8421", outputs=[{"id": "ir", "kind": "ir"}])
        device_store.learn_ir_button("sandy_ir", "tv_on", "100,200,300")

        for _ in range(3):
            node_store.ingest_status("8421", outputs=[{"id": "ir", "kind": "ir"}])

        dev = device_store.get_device("sandy_ir")
        assert (dev["meta"].get("buttons") or {}).get("tv_on") == "100,200,300", (
            "a heartbeat erased a learned button")


# ── the firmware side ────────────────────────────────────────────────────────

def test_the_board_declares_ir_and_handles_it():
    mqtt = _read("firmware/brain-core/main/sandy_mqtt.c")
    assert '{\\"id\\":\\"ir\\",\\"kind\\":\\"ir\\"}' in mqtt, (
        "the output is not declared, so no device is ever provisioned")
    assert 'strcmp(out, "ir")' in mqtt and "ir_handle(val)" in mqtt, (
        "declared with no handler — the app would draw a button that does nothing")

    cmake = _read("firmware/brain-core/main/CMakeLists.txt")
    assert '"sandy_ir.c"' in cmake, "the file exists and is not in the build"
    assert "esp_driver_rmt" in cmake, "RMT is not a dependency; the file will not link"

    main = _read("firmware/brain-core/main/sandy_main.c")
    assert "ir_init()" in main


def test_capture_is_raw_rather_than_decoded():
    """Decoding protocols is the smaller-sounding job and the one that fails on
    the customer's air conditioner. Recording the pulse train verbatim works for
    a remote whose protocol nobody has implemented."""
    ir = _read("firmware/brain-core/main/sandy_ir.c")
    assert "rmt_receive" in ir and "rmt_transmit" in ir
    for word in ("NEC", "SAMSUNG", "protocol_decode"):
        assert word not in ir, f"{word}: this is meant to be protocol-agnostic"


def test_the_carrier_is_applied():
    """Without a carrier the LED flashes and nothing in the room reacts —
    consumer receivers are tuned to 38 kHz and ignore plain light."""
    ir = _read("firmware/brain-core/main/sandy_ir.c")
    assert "rmt_apply_carrier" in ir
    assert "38000" in ir


def test_learning_and_sending_cannot_overlap():
    """Otherwise she records her own LED — cheap to prevent, confusing to
    debug."""
    ir = _read("firmware/brain-core/main/sandy_ir.c")
    assert "if (s_learning)" in ir
    assert "ignoring a send" in ir


def test_the_learned_code_is_reported_not_commanded():
    """It goes out on ir/learned, the subtopic mqtt_ingest already listens to —
    a captured code is something the board reports about itself, not an
    instruction to anyone."""
    ir = _read("firmware/brain-core/main/sandy_ir.c")
    assert 'mqtt_publish_node("ir/learned"' in ir

    ingest = _read("cloud/app/integrations/mqtt_ingest.py")
    assert '_IR_SUB = "sandy/node/+/ir/learned"' in ingest
