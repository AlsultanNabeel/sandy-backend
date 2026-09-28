"""Publish-only MQTT client for the room node (a second board on the same broker).

Topics live under the robot's own tree, so a tenant can only reach their own room
(keep in sync with room-node/room-node.ino):

    sandy/node/<id>/room/light    — "on" | "off" | "0".."100"
    sandy/node/<id>/room/color    — named color or "#rrggbb"
    sandy/node/<id>/room/music    — on|off|stop|pause|resume|next|prev, vol:N, play:F:T
    sandy/node/<id>/room/fan      — "on" | "off" | "0".."100"
    sandy/node/<id>/room/curtain  — "open" | "close"
    sandy/node/<id>/room/scene    — "<scene name>"

Broker creds: SANDY_MQTT_HOST / _PORT / _USER / _PASS. No-op when unconfigured.
"""

from __future__ import annotations

import logging
import os
import re
import ssl
import threading
import uuid
from typing import Any, Dict, Optional

import paho.mqtt.client as mqtt  # type: ignore

logger = logging.getLogger(__name__)

# Outputs on a node (same shape as the camera's "cam/flash").
ROOM_OUTPUT_PREFIX = "room/"

_DEVICE_OUTPUT = {
    "light":   ROOM_OUTPUT_PREFIX + "light",
    "color":   ROOM_OUTPUT_PREFIX + "color",
    "music":   ROOM_OUTPUT_PREFIX + "music",
    "fan":     ROOM_OUTPUT_PREFIX + "fan",
    "curtain": ROOM_OUTPUT_PREFIX + "curtain",
    "scene":   ROOM_OUTPUT_PREFIX + "scene",
}

VALID_DEVICES = frozenset(_DEVICE_OUTPUT)
_VALID_COLOR = {"warm", "cool", "white", "red", "green", "blue", "purple", "amber"}
_HEX_COLOR = re.compile(r"^#[0-9a-f]{6}$")
_MUSIC_WORDS = frozenset({"on", "off", "stop", "pause", "resume", "next", "prev"})
# DFPlayer ranges (handleMusic in room-node.ino): volume 0..30, folder 1..99, track 1..255.
_MUSIC_VOL = re.compile(r"^vol:(\d{1,2})$")
_MUSIC_PLAY = re.compile(r"^play:(\d{1,2}):(\d{1,3})$")
# A publish before the broker connects would be queued and falsely reported as sent.
_CONNECT_WAIT_S = 3.0


def _caller_node() -> Optional[Dict[str, Any]]:
    """The caller's only node, or None; with several nodes we refuse to guess which room."""
    from app.features.node_store import list_nodes

    nodes = list_nodes() or []
    if len(nodes) != 1:
        if nodes:
            logger.warning("[room_device] %d nodes paired — say which one via the "
                           "device registry", len(nodes))
        return None
    return nodes[0] if str(nodes[0].get("node_id") or "").strip() else None



def declared_room_outputs(node: Optional[Dict[str, Any]]) -> frozenset:
    """Room outputs the node's room board declared (``light``, ``music``); only these are sent."""
    outs = (node or {}).get("outputs") or []
    names = set()
    for o in outs:
        oid = str((o or {}).get("id") or "") if isinstance(o, dict) else ""
        if oid.startswith(ROOM_OUTPUT_PREFIX):
            names.add(oid[len(ROOM_OUTPUT_PREFIX):])
    return frozenset(names)


def room_topic(node_id: str, device: str) -> Optional[str]:
    output = _DEVICE_OUTPUT.get((device or "").strip().lower())
    node_id = (node_id or "").strip()
    if not output or not node_id:
        return None
    return f"sandy/node/{node_id}/{output}"


def normalize_action(device: str, value: str) -> Optional[str]:
    """Clean payload for (device, value), or None if invalid (see module docstring)."""
    device = (device or "").strip().lower()
    value = str(value or "").strip().lower()
    if device not in _DEVICE_OUTPUT or not value:
        return None
    if device in ("light", "fan"):
        if value in ("on", "off"):
            return value
        try:
            return str(max(0, min(100, int(value))))
        except ValueError:
            return None
    if device == "color":
        if value in _VALID_COLOR:
            return value
        return value if _HEX_COLOR.match(value) else None
    if device == "music":
        if value in _MUSIC_WORDS:
            return value
        m = _MUSIC_VOL.match(value)
        if m:
            return value if int(m.group(1)) <= 30 else None
        m = _MUSIC_PLAY.match(value)
        if m:
            folder, track = int(m.group(1)), int(m.group(2))
            return value if 1 <= folder <= 99 and 1 <= track <= 255 else None
        return None
    if device == "curtain":
        return value if value in ("open", "close") else None
    if device == "scene":
        return value
    return None


class RoomDeviceClient:
    """Publish-only MQTT client for the room node. No-op when unconfigured."""

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

    def send(self, device: str, value: str) -> bool:
        """Send one normalized command to the caller's own room node."""
        node = _caller_node()
        if not node:
            logger.warning("[room_device] actuation refused: no node for this caller")
            return False
        node_id = str(node.get("node_id")).strip()
        payload = normalize_action(device, value)
        if payload is None:
            return False
        name = (device or "").strip().lower()
        if name not in declared_room_outputs(node):
            logger.info("[room_device] %s skipped: the room board never declared it", name)
            return False
        topic = room_topic(node_id, device)
        if topic is None:
            return False
        return self._publish(topic, payload)


_room_client: Optional[RoomDeviceClient] = None
_room_client_lock = threading.Lock()


def get_room_device_client() -> RoomDeviceClient:
    global _room_client
    if _room_client is None:
        with _room_client_lock:
            if _room_client is None:
                _room_client = RoomDeviceClient()
    return _room_client
