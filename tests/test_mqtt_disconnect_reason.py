"""The broker says why it hung up, and we have to actually read it.

A drop used to be logged as "disconnected" with no cause, which cost a week of
guessing at a link that dropped on a regular cycle. The fix read the reason out
of the callback — and then took the wrong argument: paho's V2 signature is
``(client, userdata, disconnect_flags, reason_code, properties)`` and the code
took the first non-dict argument, which is the *flags*. Every drop logged
``DisconnectFlags(is_disconnect_packet_from_server=False)`` — true, useless, and
identical whatever the cause — while the reason sat in the next argument,
discarded, for as long as the docstring claimed otherwise.

Two shapes have to keep working, because paho has already changed this signature
once and did not ask first.
"""

from __future__ import annotations

import os

os.environ.setdefault("JWT_SECRET", "test-secret-for-mqtt")

from app.integrations import mqtt_ingest  # noqa: E402


class _DisconnectFlags:
    """Stands in for paho's own — matched by class name, as the code does."""
    __name__ = "DisconnectFlags"

    def __init__(self, from_server: bool):
        self.is_disconnect_packet_from_server = from_server

    def __repr__(self) -> str:
        return (f"DisconnectFlags(is_disconnect_packet_from_server="
                f"{self.is_disconnect_packet_from_server})")


_DisconnectFlags.__name__ = "DisconnectFlags"


class _ReasonCode:
    """paho's ReasonCode: has a value and a name, and is not a dict."""

    def __init__(self, value: int, name: str):
        self.value = value
        self._name = name

    def getName(self) -> str:      # noqa: N802 — paho's spelling
        return self._name

    def __str__(self) -> str:
        return self._name


def _reason_after(*args):
    mqtt_ingest._on_disconnect(None, None, *args)
    return mqtt_ingest._stats["last_disconnect"]


def test_the_v2_signature_reports_the_reason_not_the_flags():
    flags = _DisconnectFlags(False)
    reason = _ReasonCode(141, "Keep alive timeout")

    got = _reason_after(flags, reason, {"properties": True})

    assert got == "Keep alive timeout", (
        f"logged {got!r} — the flags again, not the reason")
    assert "DisconnectFlags" in str(mqtt_ingest._stats["last_disconnect_flags"]), (
        "the flags are still worth keeping; they just are not the reason")


def test_the_causes_are_distinguishable_from_each_other():
    """Each of these has a different fix and no two look alike — which is the
    entire point of reading the code rather than the flags."""
    flags = _DisconnectFlags(True)
    for value, name in ((142, "Session taken over"),
                        (141, "Keep alive timeout"),
                        (139, "Server shutting down"),
                        (152, "Maximum connect time")):
        assert _reason_after(flags, _ReasonCode(value, name), {}) == name


def test_the_older_signature_still_reports_its_integer():
    """paho V1 calls back with a bare rc. A TypeError raised in a callback is
    swallowed by the network loop, so the listener would look connected while
    delivering nothing."""
    assert _reason_after(7) == "7"


def test_a_drop_with_nothing_useful_does_not_raise():
    """It must log something and keep going: the callback runs on the network
    thread, and an exception there is how a client starts lying about being
    connected."""
    before = mqtt_ingest._stats["disconnects"]
    mqtt_ingest._on_disconnect(None, None)
    assert mqtt_ingest._stats["disconnects"] == before + 1


def test_the_keepalive_is_short_enough_for_a_shared_worker():
    """The listener shares a gunicorn worker with request handling and with a
    voice WebSocket that streams audio for minutes. Its ping is sent by a thread
    competing for the GIL, against a keepalive the broker measures in wall
    clock."""
    assert mqtt_ingest.MQTT_KEEPALIVE_S <= 30
    src_path = os.path.join(os.path.dirname(__file__), "..", "cloud", "app",
                            "integrations", "mqtt_ingest.py")
    with open(src_path, encoding="utf-8") as fh:
        src = fh.read()
    assert "keepalive=60" not in src, "a client is still on the old keepalive"
    assert src.count("keepalive=MQTT_KEEPALIVE_S") == 2, (
        "the watchdog's replacement client must match the original")
