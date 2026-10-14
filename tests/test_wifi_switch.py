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


# Boards from before the signed command: these tests are about the checks before anything
# is sent and the plain wire form those boards read (tests/test_signed_wifi_command.py has
# the signed one).
_OLD_FIRMWARE = {"node_id": "n1", "firmware_version": "0.11.6", "telemetry": {}}


def _sent():
    """Capture what would go to the broker."""
    return patch("app.integrations.device_publisher.get_device_publisher")


def test_a_board_you_do_not_own_is_never_touched():
    """Ownership is checked before anything leaves the server.

    Without it, any signed-in account could move somebody else's robot onto a
    network they control — which is not a privacy bug, it is handing over the
    hardware.
    """
    with patch("app.features.node_store.get_node", return_value=None), _sent() as c:
        res = wifi_switch.switch_network("someone-elses", "Net", "password")
    assert res == {"ok": False, "error": "not_yours"}
    c.assert_not_called()


def test_a_newline_cannot_be_smuggled_into_either_field():
    """The wire format is "<ssid>\\n<password>", so a newline would split it.

    Network names and passwords contain colons, commas and quotes — which is
    exactly why the separator is the one character they cannot contain. This
    test is what keeps that true if the format is ever revisited.
    """
    with patch("app.features.node_store.get_node", return_value=_OLD_FIRMWARE):
        assert wifi_switch.switch_network("n1", "Ne\nt", "password")["error"] == "bad_chars"
        assert wifi_switch.switch_network("n1", "Net", "pass\nword")["error"] == "bad_chars"


def test_impossible_credentials_are_refused_here_not_on_the_board():
    """802.11 caps an SSID at 32 bytes and a WPA passphrase at 64.

    Refusing them here costs a error message. Sending them costs twenty-five
    seconds of a robot trying to associate with something that cannot exist,
    during which it is off the network and answering nobody.
    """
    with patch("app.features.node_store.get_node", return_value=_OLD_FIRMWARE):
        assert wifi_switch.switch_network("n1", "x" * 33, "password")["error"] == "too_long"
        assert wifi_switch.switch_network("n1", "Net", "y" * 65)["error"] == "too_long"
        assert wifi_switch.switch_network("n1", "", "pw")["error"] == "no_ssid"


def test_the_name_is_counted_in_bytes_as_the_board_counts_it():
    """Seventeen Arabic letters are thirty-four bytes: past 802.11's thirty-two."""
    with patch("app.features.node_store.get_node", return_value=_OLD_FIRMWARE):
        assert wifi_switch.switch_network("n1", "ش" * 17, "password")["error"] == "too_long"
    with patch("app.features.node_store.get_node", return_value=_OLD_FIRMWARE), \
         _sent() as c:
        c.return_value.publish_service.return_value = True
        assert wifi_switch.switch_network("n1", "ش" * 16, "password")["ok"] is True


def test_a_password_wpa2_cannot_take_is_refused_before_it_is_sent():
    """A WPA2 password is 8 to 63 characters, or 64 hex digits; an open network has none.

    The board refused the rest after the request had gone, and the app said «done»."""
    with patch("app.features.node_store.get_node", return_value=_OLD_FIRMWARE), \
         _sent() as c:
        c.return_value.publish_service.return_value = True
        assert wifi_switch.switch_network("n1", "Net", "12345")["error"] == "bad_password"
        assert wifi_switch.switch_network("n1", "Net", "z" * 64)["error"] == "bad_password"
        assert wifi_switch.switch_network("n1", "Net", "ab" * 32)["ok"] is True
        assert wifi_switch.switch_network("n1", "Net", "x" * 63)["ok"] is True
        assert wifi_switch.switch_network("n1", "Net", "12345678")["ok"] is True
        assert wifi_switch.switch_network("n1", "Open", "")["ok"] is True


def test_a_good_request_reaches_the_boards_service_channel():
    with patch("app.features.node_store.get_node", return_value=_OLD_FIRMWARE), \
         _sent() as c:
        c.return_value.publish_service.return_value = True
        res = wifi_switch.switch_network("n1", "Home", "hunter22")

    assert res["ok"] is True
    topic, payload = c.return_value.publish_service.call_args[0]
    assert topic == "sandy/node/n1/wifi"
    assert payload == "Home\nhunter22"


def test_success_is_not_claimed_before_the_board_says_so():
    """`ok` means "the request was sent", and the response says how long to wait.

    A board that switched reports the new SSID in its next heartbeat; one that
    rolled back reports the old one. Treating "sent" as "done" would show the
    owner a network his robot is not on.
    """
    with patch("app.features.node_store.get_node", return_value=_OLD_FIRMWARE), \
         _sent() as c:
        c.return_value.publish_service.return_value = True
        res = wifi_switch.switch_network("n1", "Home", "password")

    assert res["window_s"] >= 25, (
        "the app would stop waiting before the board has finished trying and "
        "rolling back, and report a failure that has not happened yet")


def test_the_service_channels_are_named_one_by_one():
    """A node's service channels are named, not matched by pattern: "anything under
    sandy/node/" would let a typo reach hardware. The retired boards' are gone."""
    from app.integrations.device_publisher import DevicePublisher

    allowed = DevicePublisher._SERVICE_CHANNELS
    assert allowed == {"wifi", "screen_img", "factory_reset", "pair_code"}
    publisher = DevicePublisher()
    sent = []
    publisher._publish = lambda topic, payload: sent.append(topic) or True
    for ok in ("sandy/node/8421/wifi", "sandy/node/8421/screen_img",
               "sandy/node/8421/factory_reset", "sandy/node/8421/pair_code"):
        assert publisher.publish_service(ok, "x") is True, ok
    for bad in ("sandy/node/8421/cam/wifi", "sandy/node/8421/cam/command",
                "sandy/node/8421/room/light_arm", "sandy/node/8421/wifi/extra",
                "sandy/node//wifi", "evil/sandy/node/8421/wifi", "sandy/node/84 21/wifi"):
        assert publisher.publish_service(bad, "x") is False, bad


def test_only_the_robot_is_moved_and_an_older_apps_camera_is_refused():
    """An app from before the camera was removed may still ask for `board="camera"`. That
    is refused, never sent to the robot instead: moving the robot when the owner meant the
    camera could strand it."""
    with patch("app.features.node_store.get_node", return_value=_OLD_FIRMWARE), \
         _sent() as c:
        c.return_value.publish_service.return_value = True

        wifi_switch.switch_network("n1", "Home", "password")
        assert c.return_value.publish_service.call_args[0][0] == "sandy/node/n1/wifi"
        c.reset_mock()
        for board in ("camera", "room", "nonsense"):
            assert wifi_switch.switch_network("n1", "Home", "password",
                                              board=board)["error"] == "bad_board"
        c.return_value.publish_service.assert_not_called()


def test_every_channel_that_is_not_a_device_uses_the_service_path():
    """The same routing bug has now been found three times.

    `send_to_topic` authorises by asking "is there a **device** whose transport
    builds this topic?" — right for a control, wrong for a channel, because no
    device declares a channel and the publish is refused with nothing said.

    It cost the picture on the display (`screen_img`): text worked and pictures did not, which reads like an image
    problem and was a routing one. This test is the pattern rather than the
    instance: anything published to a topic no device declares goes through
    `publish_service`.
    """
    import re
    from pathlib import Path

    from app.integrations.device_publisher import DevicePublisher

    channels = {"wifi", "screen_img", "factory_reset", "pair_code"}
    allowed = DevicePublisher._SERVICE_CHANNELS
    for ch in channels:
        assert any(a.strip("/") in ch for a in allowed), (
            f"{ch} is a channel but no service entry allows it — every publish "
            "to it will be refused, silently")

    # And no caller may reach a channel through the device path.
    src_dir = Path(__file__).resolve().parent.parent / "cloud" / "app"
    offenders = []
    for path in src_dir.rglob("*.py"):
        for line in re.findall(r".*send_to_topic\(.*", path.read_text(encoding="utf-8")):
            if line.strip().startswith("#"):
                continue
            if any(ch in line for ch in ("screen_img", "/wifi", "factory_reset", "pair_code")):
                offenders.append(f"{path.name}: {line.strip()[:70]}")
    assert not offenders, (
        "a channel is being published through the device path again — it will "
        f"be refused and nothing will say why: {offenders}")
