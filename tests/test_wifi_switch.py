"""Moving a board to another network without stranding it.

The whole feature is one risk: the only way to reach a board is the network it is
on, so a wrong password takes away the channel you would use to correct it. These
tests cover the server's half — refuse what cannot work, never touch a board that
is not yours, and never claim success the board has not reported.

The rollback itself lives in the firmware (`wifi_sandy_switch`), because it has to
work when the server is exactly what became unreachable.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

from app.features import wifi_switch  # noqa: E402


def _sent():
    """Capture what would go to the broker."""
    return patch("app.integrations.room_device.get_room_device_client")


def test_a_board_you_do_not_own_is_never_touched():
    """Ownership is checked before anything leaves the server.

    Without it, any signed-in account could move somebody else's robot onto a
    network they control — which is not a privacy bug, it is handing over the
    hardware.
    """
    with patch("app.features.node_store.get_node", return_value=None), _sent() as c:
        res = wifi_switch.switch_network("someone-elses", "Net", "pw")
    assert res == {"ok": False, "error": "not_yours"}
    c.assert_not_called()


def test_a_newline_cannot_be_smuggled_into_either_field():
    """The wire format is "<ssid>\\n<password>", so a newline would split it.

    Network names and passwords contain colons, commas and quotes — which is
    exactly why the separator is the one character they cannot contain. This
    test is what keeps that true if the format is ever revisited.
    """
    with patch("app.features.node_store.get_node", return_value={"node_id": "n1"}):
        assert wifi_switch.switch_network("n1", "Ne\nt", "pw")["error"] == "bad_chars"
        assert wifi_switch.switch_network("n1", "Net", "p\nw")["error"] == "bad_chars"


def test_impossible_credentials_are_refused_here_not_on_the_board():
    """802.11 caps an SSID at 32 bytes and a WPA passphrase at 64.

    Refusing them here costs a error message. Sending them costs twenty-five
    seconds of a robot trying to associate with something that cannot exist,
    during which it is off the network and answering nobody.
    """
    with patch("app.features.node_store.get_node", return_value={"node_id": "n1"}):
        assert wifi_switch.switch_network("n1", "x" * 33, "pw")["error"] == "too_long"
        assert wifi_switch.switch_network("n1", "Net", "y" * 65)["error"] == "too_long"
        assert wifi_switch.switch_network("n1", "", "pw")["error"] == "no_ssid"


def test_a_good_request_reaches_the_boards_service_channel():
    with patch("app.features.node_store.get_node", return_value={"node_id": "n1"}), \
         _sent() as c:
        c.return_value.publish_service.return_value = True
        res = wifi_switch.switch_network("n1", "Home", "hunter2")

    assert res["ok"] is True
    topic, payload = c.return_value.publish_service.call_args[0]
    assert topic == "sandy/node/n1/wifi"
    assert payload == "Home\nhunter2"


def test_success_is_not_claimed_before_the_board_says_so():
    """`ok` means "the request was sent", and the response says how long to wait.

    A board that switched reports the new SSID in its next heartbeat; one that
    rolled back reports the old one. Treating "sent" as "done" would show the
    owner a network his robot is not on.
    """
    with patch("app.features.node_store.get_node", return_value={"node_id": "n1"}), \
         _sent() as c:
        c.return_value.publish_service.return_value = True
        res = wifi_switch.switch_network("n1", "Home", "pw")

    assert res["window_s"] >= 25, (
        "the app would stop waiting before the board has finished trying and "
        "rolling back, and report a failure that has not happened yet")


def test_the_service_channel_allows_wifi_and_the_camera_and_nothing_else():
    """A node's service channels are named, not matched by pattern.

    "Anything under sandy/node/" would let a typo reach hardware; "anything with
    cam/ in it" silently blocks every channel added later — which is what
    happened when this one was added.
    """
    from app.integrations.room_device import RoomDeviceClient

    allowed = RoomDeviceClient._SERVICE_CHANNELS
    assert "/wifi" in allowed and "/cam/" in allowed
    assert not any(c in ("/", "sandy/node/") for c in allowed), (
        "a channel this broad authorises everything")
