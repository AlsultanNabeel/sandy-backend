"""Publish-only MQTT client for every board's commands (the robot, its camera, its room node).

A device is sent to by its topic (`send_to_topic`), once `device_store.command_payload`
has validated the value and only when the topic is one of the caller's own devices; a
node's service channels (camera, network) go through `publish_service`.

Broker creds: SANDY_MQTT_HOST / _PORT / _USER / _PASS. No-op when unconfigured.
"""

from __future__ import annotations

import logging
import os
import re
import ssl
import threading
import uuid
from typing import Any, Optional

import paho.mqtt.client as mqtt  # type: ignore

logger = logging.getLogger(__name__)

# A publish before the broker connects would be queued and falsely reported as sent.
_CONNECT_WAIT_S = 3.0


class RoomDeviceClient:
    """Publish-only MQTT client. No-op when unconfigured."""

    def __init__(self):
        self._host = os.getenv("SANDY_MQTT_HOST", "").strip()
        self._user = os.getenv("SANDY_MQTT_USER", "").strip()
        self._pass = os.getenv("SANDY_MQTT_PASS", "").strip()
        try:
            self._port = int(os.getenv("SANDY_MQTT_PORT", "8883"))
        except ValueError:
            self._port = 8883
        self._client: Optional[Any] = None
        self._lock = threading.RLock()
        self._connected = threading.Event()

    @property
    def available(self) -> bool:
        return bool(self._host and self._user and self._pass)

    def _ensure_client(self) -> Optional[Any]:
        if not self.available:
            return None
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                c = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    # Unique id: dynos share pids, and duplicate ids kick each other off.
                    client_id=f"sandy-room-{os.getpid()}-{uuid.uuid4().hex[:8]}",
                    clean_session=True,
                )
                c.username_pw_set(self._user, self._pass)
                c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
                c.on_connect = self._on_connect
                c.on_disconnect = self._on_disconnect
                # Async so a request never blocks on the TLS handshake.
                c.connect_async(self._host, self._port, keepalive=60)
                c.loop_start()
                self._client = c
                return c
            except Exception as e:  # noqa: BLE001
                logger.warning("[room_device] MQTT connect failed: %s", e)
                self._client = None
                return None

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ANN001
        if getattr(reason_code, "is_failure", False) or (
                isinstance(reason_code, int) and reason_code != 0):
            logger.warning("[room_device] broker refused: %s", reason_code)
            self._connected.clear()
            return
        self._connected.set()

    def _on_disconnect(self, client, userdata, *args) -> None:  # noqa: ANN001
        self._connected.clear()

    def _publish(self, topic: str, payload: str) -> bool:
        c = self._ensure_client()
        if c is None:
            return False
        if not self._connected.wait(_CONNECT_WAIT_S):
            logger.warning("[room_device] broker not connected — %s not sent", topic)
            return False
        try:
            return c.publish(topic, payload, qos=1).rc == 0
        except Exception as e:  # noqa: BLE001
            logger.warning("[room_device] publish failed (%s): %s", topic, e)
            return False

    def send_to_topic(self, topic: str, payload: str) -> bool:
        """Publish a pre-validated payload to a device topic owned by the calling tenant."""
        topic = (topic or "").strip()
        if not topic:
            return False
        from app.features.device_store import tenant_owns_topic

        if not tenant_owns_topic(topic):
            logger.warning("[room_device] send_to_topic refused: topic not owned by caller")
            return False
        return self._publish(topic, str(payload))

    # Exact allowlist of service channels (full match, not substring).
    _SERVICE_CHANNELS = frozenset({
        "cam/command", "cam/request", "cam/wifi", "wifi", "screen_img",
        "factory_reset", "pair_code",
    })
    _SERVICE_TOPIC = re.compile(r"^sandy/node/([a-z0-9]{1,64})/(.+)$")

    def publish_service(self, topic: str, payload: str) -> bool:
        """Publish on a node's service channel (camera, network — not devices).

        Ownership of the node is checked by the caller.
        """
        topic = (topic or "").strip()
        m = self._SERVICE_TOPIC.match(topic)
        if not m or m.group(2) not in self._SERVICE_CHANNELS:
            logger.warning("[room_device] publish_service refused: %s", topic)
            return False
        return self._publish(topic, str(payload))


_room_client: Optional[RoomDeviceClient] = None
_room_client_lock = threading.Lock()


def get_room_device_client() -> RoomDeviceClient:
    global _room_client
    if _room_client is None:
        with _room_client_lock:
            if _room_client is None:
                _room_client = RoomDeviceClient()
    return _room_client
