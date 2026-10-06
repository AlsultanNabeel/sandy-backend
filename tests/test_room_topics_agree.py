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
import re
from pathlib import Path

import mongomock
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-room-topics")

from app.features import device_store, node_store  # noqa: E402
from app.utils.user_profiles import active_user_profile_context  # noqa: E402

_ROOT = Path(__file__).resolve().parent.parent


# The room node's device table — one row per output, name and kind, and the
# heartbeat is built from it (`{ "light", "relay", handleLight }`).
_ROOM_TABLE = re.compile(r'\{\s*"(\w+)",\s*"(\w+)",\s*handle\w+\s*\}')


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


def test_the_room_heartbeat_declares_kinds_the_server_accepts():
    """An unknown `kind` is dropped silently, and the device never appears.

    That failure has no error anywhere: the board publishes, the server parses,
    the entry is discarded, and the app is simply missing a lamp. So the two
    ends are pinned to each other here.
    """
    from app.features.node_store import KNOWN_CAPABILITIES

    ino = _read("firmware/room-node/room-node.ino")
    kinds = {k for _, k in _ROOM_TABLE.findall(ino)}
    assert kinds, "the room heartbeat declares no outputs at all"
    assert kinds <= set(KNOWN_CAPABILITIES), (
        f"room node declares kinds the server drops: {kinds - set(KNOWN_CAPABILITIES)}")


def test_every_declared_room_output_has_a_catalogue_entry():
    """A declared output with no catalogue row is ignored, not drawn."""
    from app.features.node_provision import PART_CATALOGUE

    ino = _read("firmware/room-node/room-node.ino")
    declared = {name for name, _ in _ROOM_TABLE.findall(ino)}
    assert declared == {"light", "music"}
    for out in declared:
        assert f"room/{out}" in PART_CATALOGUE, (
            f"the room node declares {out} and the catalogue cannot draw it")


def test_the_server_listens_to_the_room_heartbeat():
    """The subscription is the difference between working and invisible."""
    src = _read("cloud/app/integrations/mqtt_ingest.py")
    assert '_ROOM_STATUS_SUB = "sandy/node/+/room/status"' in src
    assert "_ROOM_STATUS_SUB, 1" in src, "declared but never subscribed"
    assert '"/room/status"' in src, "subscribed but never routed"


# ── the two firmwares ────────────────────────────────────────────────────────

def test_no_global_room_tree_is_left_in_any_firmware():
    for rel in ("firmware/brain-core/main/sandy_voice.c",
                "firmware/brain-core/main/sandy_mqtt.c",
                "firmware/room-node/room-node.ino"):
        src = _read(rel)
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("//"))
        assert "room/cmd" not in code, (
            f"{rel} still publishes or listens on the global room tree")


def test_the_brain_publishes_under_its_own_node():
    fw = _read("firmware/brain-core/main/sandy_mqtt.c")
    # Every outgoing topic is built in one place, from the node's own base.
    assert '"%s/%s", s_base, suffix' in fw, (
        "the brain no longer builds its topics from its own node base")
    assert '"room/%s", out' in fw, "the room prefix is gone"

    voice = _read("firmware/brain-core/main/sandy_voice.c")
    # Bare output names in the command table — a full topic here would be
    # concatenated into sandy/node/<id>/room/room/cmd/light and land nowhere.
    for out in ('"light"', '"fan"', '"music"'):
        assert f"CMD_ROOM,   {out}," in voice, f"command table lost {out}"


def test_the_brain_ignores_outputs_that_belong_to_other_boards():
    """The brain subscribes to the whole tree, so it receives the room's traffic.

    Without an explicit skip, every camera and room message logged "unknown
    output" — and a warning that fires on normal traffic is a warning nobody
    reads when something is actually wrong.
    """
    fw = _read("firmware/brain-core/main/sandy_mqtt.c")
    assert 'strncmp(out, "cam/", 4)' in fw
    assert 'strncmp(out, "room/", 5)' in fw


def test_the_room_node_listens_on_its_own_tree():
    ino = _read("firmware/room-node/room-node.ino")
    assert '"sandy/node/" + g_nodeId + "/room"' in ino
    # One exact topic per declared output — a wildcard also delivered the node's
    # own heartbeat back to it, and anything anyone wrote under the tree.
    assert 'String topic = g_topicBase + "/" + DEVICES[i].name;' in ino
    assert "g_mqtt.subscribe(topic.c_str(), 1)" in ino
    assert '"/#"' not in ino
    # Its heartbeat moves with it; a status left on the old tree would be one
    # customer's room reporting into everybody's.
    assert 'g_topicStatus = g_topicBase + "/status"' in ino
    assert "SANDY_PAIR_CODE" in _read("firmware/room-node/secrets.example.h"), (
        "the room node has no pairing code, so it cannot know which tree is its")


def test_all_three_firmwares_derive_the_node_id_identically():
    """Lowercase, alphanumerics only, from the pairing code.

    Three separate implementations of one rule. If they ever disagree, two boards
    sit on two trees and the symptom is "the command did nothing" with no error
    anywhere — so the rule is pinned here rather than trusted.
    """
    sources = {
        "brain": _read("firmware/brain-core/main/sandy_mqtt.c"),
        "camera": _read("firmware/vision-core/cam_mqtt.ino"),
        "room": _read("firmware/room-node/room-node.ino"),
    }
    for name, src in sources.items():
        assert re.search(r"c\s*-\s*'A'\s*\+\s*'a'", src), (
            f"{name} no longer lowercases the pairing code")
        assert re.search(r"c >= 'a' && c <= 'z'\) \|\| \(c >= '0' && c <= '9'", src), (
            f"{name} no longer strips the pairing code to alphanumerics")
