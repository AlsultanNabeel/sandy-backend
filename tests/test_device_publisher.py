"""The server's one publisher for the robot's commands (integrations/device_publisher)."""
from __future__ import annotations


def test_a_publish_waits_for_the_broker_and_then_says_no():
    """Publishing into a client that never connected used to report success."""
    import app.integrations.device_publisher as dp

    client = dp.DevicePublisher()

    class _Fake:
        def publish(self, *a, **k):   # pragma: no cover - must not be reached
            raise AssertionError("published without a connection")

    client._ensure_client = lambda: _Fake()   # type: ignore[method-assign]
    old = dp._CONNECT_WAIT_S
    dp._CONNECT_WAIT_S = 0.01
    try:
        assert client._publish("sandy/node/8421/volume", "40") is False
    finally:
        dp._CONNECT_WAIT_S = old
