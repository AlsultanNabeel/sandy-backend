"""The room light's arm, set up from the app (features/room_arm.py).

What matters: only the owner's board is moved, nothing the servo cannot do is sent, a
trial press is a trial (it never touches the light's saved state), and the heartbeat's
saved setup reaches the app.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

from app.features import room_arm  # noqa: E402

ONLINE = {"node_id": "n1", "telemetry": {"room_online": True}}
GOOD = {"rest": 120, "on": 80, "off": 160, "hold_ms": 400}


def _client():
    return patch("app.integrations.room_device.get_room_device_client")


def test_each_action_has_its_wire_form():
    assert room_arm.wire_command({"action": "goto", "angle": 95}) == ("goto:95", None)
    assert room_arm.wire_command({"action": "save", **GOOD}) == ("set:120,80,160,400", None)
    assert room_arm.wire_command({"action": "try_on", **GOOD}) == ("try:on:120,80,160,400", None)
    assert room_arm.wire_command({"action": "try_off", **GOOD}) == ("try:off:120,80,160,400", None)


def test_what_the_servo_cannot_do_is_refused_here():
    """The board checks the same limits; refusing here gives the app a reason to show."""
    w = room_arm.wire_command
    assert w({"action": "goto", "angle": 5})[1] == "angle_out_of_range"
    assert w({"action": "goto", "angle": "x"})[1] == "angle_out_of_range"
    assert w({"action": "save", **GOOD, "off": 175})[1] == "angle_out_of_range"
    assert w({"action": "save", **GOOD, "hold_ms": 100})[1] == "hold_out_of_range"
    assert w({"action": "save", **GOOD, "hold_ms": 2000})[1] == "hold_out_of_range"
    assert w({"action": "save", "rest": 120, "on": 80})[1] == "missing_values"
    assert w({"action": "spin"})[1] == "bad_action"


def test_rest_must_sit_between_the_two_presses():
    """A rest at or past one press leaves the arm pressing the switch while it rests."""
    w = room_arm.wire_command
    assert w({"action": "save", **GOOD, "rest": 85})[1] == "rest_not_between"
    assert w({"action": "save", **GOOD, "rest": 165})[1] == "rest_not_between"
    # Either side can be "on": the switch may be mounted upside down.
    assert w({"action": "save", "rest": 120, "on": 160, "off": 80, "hold_ms": 400})[1] is None


def test_a_board_you_do_not_own_is_never_moved():
    with patch("app.features.node_store.get_node", return_value=None), _client() as c:
        reply, status = room_arm.command("someone-elses", {"action": "goto", "angle": 90})
    assert (reply["error"], status) == ("not_found", 404)
    c.assert_not_called()


def test_a_room_node_that_is_not_there_is_said_so():
    off = {"node_id": "n1", "telemetry": {"room_online": False}}
    with patch("app.features.node_store.get_node", return_value=off), _client() as c:
        reply, status = room_arm.command("n1", {"action": "goto", "angle": 90})
    assert (reply["error"], status) == ("room_offline", 409)
    c.assert_not_called()


def test_a_trial_press_goes_to_the_service_channel_and_leaves_the_light_alone():
    """Not through send_to_topic or device_control: nothing records a light state."""
    with patch("app.features.node_store.get_node", return_value=ONLINE), _client() as c, \
         patch("app.features.device_store.set_state") as set_state:
        c.return_value.publish_service.return_value = True
        reply, status = room_arm.command("n1", {"action": "try_off", **GOOD})
    assert (reply, status) == ({"ok": True}, 200)
    c.return_value.publish_service.assert_called_once_with(
        "sandy/node/n1/room/light_arm", "try:off:120,80,160,400")
    c.return_value.send_to_topic.assert_not_called()
    set_state.assert_not_called()


def test_a_broker_that_did_not_take_it_is_not_reported_as_sent():
    with patch("app.features.node_store.get_node", return_value=ONLINE), _client() as c:
        c.return_value.publish_service.return_value = False
        reply, status = room_arm.command("n1", {"action": "save", **GOOD})
    assert (reply["error"], status) == ("not_sent", 503)


def test_the_service_channel_is_allowed_and_nothing_wider():
    from app.integrations.room_device import RoomDeviceClient

    client = RoomDeviceClient.__new__(RoomDeviceClient)
    with patch.object(RoomDeviceClient, "_publish", return_value=True) as pub:
        assert client.publish_service("sandy/node/n1/room/light_arm", "goto:90")
        assert not client.publish_service("sandy/node/n1/room/light", "on")
    pub.assert_called_once_with("sandy/node/n1/room/light_arm", "goto:90")


def test_the_saved_setup_reaches_the_app_through_the_heartbeat():
    import json

    from app.integrations import mqtt_ingest

    beat = {"online": True, "light": "off", "arm": "118,82,158,500",
            "outputs": [{"id": "light", "kind": "relay"}]}
    with patch("app.features.node_store.ingest_status") as ingest:
        mqtt_ingest._ingest_room_status("n1", json.dumps(beat))
    tel = ingest.call_args.kwargs["telemetry"]
    assert tel["room_arm"] == "118,82,158,500"

    from app.features.node_store import _clean_telemetry
    assert _clean_telemetry({"room_arm": "118,82,158,500"}) == {"room_arm": "118,82,158,500"}
