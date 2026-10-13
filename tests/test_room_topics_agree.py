"""The room node lives on the robot's own topic tree, and both ends agree on it.

The room commands used to be six fixed global strings — ``room/cmd/light`` and
friends. Nothing in them said whose room it was, so every room node ever flashed
listened to all of them: one person's "lights off" was every person's. The cloud
worked around it by refusing everyone except the owner, which made the feature
unusable for a second customer rather than unsafe for them.

It cost money too. The brain had to reach its own tree *and* that global one,
and a broker credential on the free plan carries exactly one topic filter — so
per-device broker keys could not be expressed at all without a paid plan.

Everything now hangs under ``sandy/node/<node_id>/room/…``. These tests pin the
two things that silently break if only one end is edited: the topic shape, and
the node id derivation that has to match character for character across three
firmwares.
"""

from __future__ import annotations

import os
from pathlib import Path

import mongomock
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-room-topics")

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


# ── the topic itself ─────────────────────────────────────────────────────────

def test_a_room_output_is_on_its_own_robots_tree():
    """A room output is an output on a node, exactly like the camera's "cam/flash"."""
    def topic(node_id):
        return device_store.device_topic(
            {"transport": {"kind": "node", "node_id": node_id, "output": "room/light"}})

    assert topic("8421") == "sandy/node/8421/room/light"
    # Two robots, two rooms. This is the whole point of the move.
    assert topic("9999") != topic("8421")


def test_ownership_of_a_room_topic_is_a_tenant_lookup(db):
    """Every tenant reaches their own room, and only their own.

    The old global topics forced a blunt "owner only" rule. Now the topic names
    the node, so the ordinary per-tenant check does the work — which is what
    makes the room usable by a second customer at all.
    """
    with as_tenant("tenant-a"):
        paired = node_store.pair_node("8421", label="غرفتي")
        assert paired.get("ok"), paired
        node_id = paired["node_id"]
        # The pairing code the owner types is the node id the topics carry.
        assert node_id == "8421"

        added = device_store.add_device(
            name="room_light", label="ضوء الغرفة", control_type="switch",
            transport={"kind": "node", "node_id": node_id, "output": "room/light"},
            room="غرفتي",
        )
        assert added.get("ok"), added
        topic = f"sandy/node/{node_id}/room/light"
        assert device_store.tenant_owns_topic(topic) is True

    with as_tenant("tenant-b"):
        assert device_store.tenant_owns_topic(topic) is False


def test_service_channels_match_exactly():
    from app.integrations.room_device import RoomDeviceClient

    client = RoomDeviceClient()
    sent = []
    client._publish = lambda topic, payload: sent.append(topic) or True  # type: ignore[method-assign]
    for ok in ("sandy/node/8421/cam/command", "sandy/node/8421/wifi",
               "sandy/node/8421/cam/wifi", "sandy/node/8421/screen_img",
               "sandy/node/8421/factory_reset"):
        assert client.publish_service(ok, "x") is True, ok
    for bad in ("sandy/node/8421/room/wifi_evil", "sandy/node/8421/cam/anything",
                "sandy/node/8421/wifi/extra", "sandy/node//wifi",
                "evil/sandy/node/8421/wifi", "sandy/node/84 21/wifi"):
        assert client.publish_service(bad, "x") is False, bad


def test_a_publish_waits_for_the_broker_and_then_says_no():
    """Publishing into a client that never connected used to report success."""
    import app.integrations.room_device as rd

    client = rd.RoomDeviceClient()

    class _Fake:
        def publish(self, *a, **k):   # pragma: no cover - must not be reached
            raise AssertionError("published without a connection")

    client._ensure_client = lambda: _Fake()   # type: ignore[method-assign]
    old = rd._CONNECT_WAIT_S
    rd._CONNECT_WAIT_S = 0.01
    try:
        assert client._publish("sandy/node/8421/room/light", "on") is False
    finally:
        rd._CONNECT_WAIT_S = old


# ── the room declares itself ─────────────────────────────────────────────────

def test_three_boards_under_one_node_keep_their_own_outputs(db):
    """Brain, camera and room node share a node id and take turns heartbeating.

    Each writes in its own prefix and must leave the others alone. The rule used
    to be a boolean — camera or not — which was correct with two boards and
    silently wrong with three: the room's outputs read as "not camera", so every
    brain heartbeat deleted the room and every room heartbeat deleted the brain,
    five seconds apart, for ever.
    """
    with as_tenant("tenant-a"):
        node_store.pair_node("8421", label="ساندي")

        node_store.ingest_status("8421", outputs=[{"id": "servo", "kind": "servo"}])
        node_store.ingest_status("8421", outputs=[{"id": "cam/flash", "kind": "relay"}])
        node_store.ingest_status("8421", outputs=[{"id": "room/light", "kind": "relay"}])

        ids = {o["id"] for o in (node_store.get_node("8421") or {}).get("outputs", [])}
        assert ids == {"servo", "cam/flash", "room/light"}

        # And a second heartbeat from one board replaces only its own namespace.
        node_store.ingest_status("8421", outputs=[{"id": "room/music", "kind": "audio"}])
        ids = {o["id"] for o in (node_store.get_node("8421") or {}).get("outputs", [])}
        assert ids == {"servo", "cam/flash", "room/music"}

        # Declaring nothing keeps everything: silence is not a claim that the
        # hardware is gone.
        node_store.ingest_status("8421", outputs=[])
        ids2 = {o["id"] for o in (node_store.get_node("8421") or {}).get("outputs", [])}
        assert ids2 == ids


def test_the_room_lamp_becomes_a_device_on_its_own(db):
    """Pair the code, power the room node, and the lamp is in the app.

    The owner must never have to describe his own hardware to his own app. This
    is the whole path: the board declares an output, the catalogue says how to
    draw it, provisioning creates the device, and its topic points back at the
    board that declared it.
    """
    with as_tenant("tenant-a"):
        node_store.pair_node("8421", label="غرفتي")
        node_store.ingest_status("8421", outputs=[
            {"id": "room/light", "kind": "relay"},
            {"id": "room/music", "kind": "audio"},
        ])

        lamp = device_store.get_device("room_light")
        assert lamp is not None, "the room node declared a lamp and no device appeared"
        assert lamp["control_type"] == "switch"
        assert device_store.device_topic(lamp) == "sandy/node/8421/room/light"

        music = device_store.get_device("room_music")
        assert music is not None
        assert "stop" in music["meta"]["values"]


def test_the_server_listens_to_the_room_heartbeat():
    """The subscription is the difference between working and invisible."""
    src = _read("cloud/app/integrations/mqtt_ingest.py")
    assert '_ROOM_STATUS_SUB = "sandy/node/+/room/status"' in src
    assert "_ROOM_STATUS_SUB, 1" in src, "declared but never subscribed"
    assert '"/room/status"' in src, "subscribed but never routed"
