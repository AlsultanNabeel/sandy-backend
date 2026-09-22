"""Room Device Client — MQTT control for the room node (lights/music/fan/curtain).

A SECOND physical board on the SAME HiveMQ broker as the robot body. The room
node is a classic ESP32 running `room-node/room-node.ino` (light servo + DFPlayer). This client is **publish-only** for now — it fires
room commands and is a graceful no-op when MQTT isn't configured, so scenes can
be wired and tested before the hardware is online.

Topics (the cloud↔room-node contract — keep firmware in sync). They live under
the robot's own tree, the same namespace the brain and the camera use:

    sandy/node/<node_id>/room/light    — "on" | "off" | "0".."100"  (brightness %)
    sandy/node/<node_id>/room/color    — "warm" | "cool" | "white" | "red" |
                        "green" | "blue" | "purple" | "amber"  (or "#rrggbb")
    sandy/node/<node_id>/room/music    — "on" | "off" | "stop" | "pause" | "resume" | "next" | "prev"
    sandy/node/<node_id>/room/fan      — "on" | "off" | "0".."100"
    sandy/node/<node_id>/room/curtain  — "open" | "close"
    sandy/node/<node_id>/room/scene    — "<scene name>"  (optional: let the node
                        run a named scene locally; the cloud also sends the
                        individual commands)

They were six fixed global strings — ``room/cmd/light`` and friends — carrying
no device identity, so every room node ever flashed listened to all of them and
one tenant's "lights off" would have reached every other tenant's room. The only
safe answer then was to refuse everyone except the owner, which is what this
module did.

Moving them under the node's own tree is what lets that restriction go: the
topic now names whose room it is, so every tenant can drive their own hardware
and nobody can reach anyone else's. It also makes the broker permission
writable — the brain needs one topic filter now instead of two, and a credential
on the free plan carries exactly one.

Reuses the robot's broker creds (in .env — never commit):
    SANDY_MQTT_HOST / SANDY_MQTT_PORT / SANDY_MQTT_USER / SANDY_MQTT_PASS
"""

from __future__ import annotations

import logging
import os
import re
import ssl
import threading
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt  # type: ignore
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# The room outputs, by name. These are *outputs* on a node, not whole topics —
# the same shape the camera uses ("cam/flash"), so device_store.device_topic
# builds them the one way it builds every other node topic.
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
# The DFPlayer's own ranges (handleMusic in room-node.ino): volume 0..30,
# folder 1..99, track 1..255. Anything else the board would ignore anyway —
# refusing it here is what lets the caller hear "that did not happen".
_MUSIC_VOL = re.compile(r"^vol:(\d{1,2})$")
_MUSIC_PLAY = re.compile(r"^play:(\d{1,2}):(\d{1,3})$")
# How long the first command waits for the broker before saying no. A publish
# into a client that is not connected yet was queued and reported as sent —
# the scene "worked" and the lamp never moved.
_CONNECT_WAIT_S = 3.0


def _caller_node() -> Optional[Dict[str, Any]]:
    """The node whose room this caller may drive, or None.

    Reads the caller's own nodes, so the answer is scoped to the tenant by
    construction and there is no separate ownership rule to keep in step.

    **More than one node is refused rather than guessed.** This entry point takes
    a device name and no node, so with two robots paired there is no honest way
    to say which room "turn the light off" meant — and picking one would work
    silently until the day it picked wrong. Callers that know which node they
    mean go through the device registry, where the node travels with the device.
    """
    from app.features.node_store import list_nodes

    nodes = list_nodes() or []
    if len(nodes) != 1:
        if nodes:
            logger.warning("[room_device] %d nodes paired — say which one via the "
                           "device registry", len(nodes))
        return None
    return nodes[0] if str(nodes[0].get("node_id") or "").strip() else None


def _caller_node_id() -> Optional[str]:
    node = _caller_node()
    return str(node.get("node_id")).strip() if node else None


def declared_room_outputs(node: Optional[Dict[str, Any]]) -> frozenset:
    """The room outputs this node's room board said it has (``light``, ``music``).

    A command for an output nobody declared used to go out anyway: the broker
    took it, the call reported success, and nothing in the house moved — the
    room node answered "no handler" to its own serial port. Only what the board
    announced in its heartbeat is sent now; the rest is reported as skipped.
    """
    outs = (node or {}).get("outputs") or []
    names = set()
    for o in outs:
        oid = str((o or {}).get("id") or "") if isinstance(o, dict) else ""
        if oid.startswith(ROOM_OUTPUT_PREFIX):
            names.add(oid[len(ROOM_OUTPUT_PREFIX):])
    return frozenset(names)


def room_topic(node_id: str, device: str) -> Optional[str]:
    """``sandy/node/<node_id>/room/<device>`` — one place that builds it."""
    output = _DEVICE_OUTPUT.get((device or "").strip().lower())
    node_id = (node_id or "").strip()
    if not output or not node_id:
        return None
    return f"sandy/node/{node_id}/{output}"


def normalize_action(device: str, value: str) -> Optional[str]:
    """Return a clean payload for (device, value), or None if invalid.

    Light/fan accept on|off or a 0..100 brightness/speed; color accepts a named
    color or #rrggbb; music accepts on|off, the player's own
    stop|pause|resume|next|prev, ``vol:0..30`` and ``play:<folder>:<track>``
    (``handleMusic`` in room-node.ino); curtain open|close.
    """
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
        return MQTT_AVAILABLE and bool(self._host and self._user and self._pass)

    def _ensure_client(self) -> Optional[Any]:
        if not self.available:
            return None
        with self._lock:
            if self._client is not None:
                return self._client
            try:
                c = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    # Unique per process: during a deploy the old and new dyno
                    # share pids, and one broker id kicked the other off in a
                    # loop (mqtt_ingest fixed the same collision). Publish-only,
                    # so there is no session worth keeping.
                    client_id=f"sandy-room-{os.getpid()}-{uuid.uuid4().hex[:8]}",
                    clean_session=True,
                )
                c.username_pw_set(self._user, self._pass)
                c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
                c.on_connect = self._on_connect
                c.on_disconnect = self._on_disconnect
                # Async: a blocking connect held the caller's request — a voice
                # turn — for the whole TLS handshake, and a broker that was down
                # held it for the socket timeout. The network thread connects
                # and reconnects on its own; `_publish` waits a bounded moment.
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
        """Publish a pre-validated payload to an arbitrary device topic.

        Used by the device registry, where each device carries its own MQTT topic
        (the payload is already validated by device_store.command_payload).

        Ownership is enforced HERE, at the boundary, not at the call sites: the
        topic must belong to a device registered to the **calling tenant**. That
        check is a tenant-scoped read, so it is every tenant's own hardware that
        opens up — and another tenant's topic that stays shut, even if a caller
        upstream forgot to look. A tenant with no such device gets False.
        """
        topic = (topic or "").strip()
        if not topic:
            return False
        from app.features.device_store import tenant_owns_topic

        if not tenant_owns_topic(topic):
            logger.warning("[room_device] send_to_topic refused: topic not owned by caller")
            return False
        return self._publish(topic, str(payload))

    # القنوات الخدمية المسموحة، بالاسم.
    #
    # قائمة صريحة مش نمط: «أي إشي تحت sandy/node/» بيسمح لأي خطأ إملائي يوصل
    # للوح، و«أي إشي فيه cam/» بيمنع أي قناة جديدة بصمت. الاسم الصريح بيخلّي
    # إضافة قناة قرارًا مكتوبًا، وبيخلّي المنع مقروءًا.
    #
    # **مطابقة كاملة للقناة، مش «فيها».** «فيها /wifi» كانت بتمرّق
    # `sandy/node/x/room/wifi_evil` و«فيها /cam/» كانت بتمرّق أي إشي تحت
    # الكاميرا. هلّق الموضوع لازم يكون `sandy/node/<معرّف>/<قناة>` حرفيًّا.
    _SERVICE_CHANNELS = frozenset({
        "cam/command", "cam/request", "cam/wifi", "wifi", "screen_img",
        "factory_reset", "pair_code",
    })
    _SERVICE_TOPIC = re.compile(r"^sandy/node/([a-z0-9]{1,64})/(.+)$")

    def publish_service(self, topic: str, payload: str) -> bool:
        """Publish on a node's service channel (camera, network — not devices).

        Separate from `send_to_topic` because the two authorise differently and
        conflating them is what broke the camera. `send_to_topic` asks "is there
        a device whose transport builds this topic?" — right for a control, and
        wrong for `cam/command`, which is a channel rather than a device, so
        every publish was refused with no error anyone could see.

        The ownership check for this one lives at the call site, where the thing
        being checked is the node. Keeping it there rather than duplicating a
        second rule here means there is exactly one place per channel that
        decides, instead of two that can disagree.
        """
        topic = (topic or "").strip()
        m = self._SERVICE_TOPIC.match(topic)
        if not m or m.group(2) not in self._SERVICE_CHANNELS:
            logger.warning("[room_device] publish_service refused: %s", topic)
            return False
        return self._publish(topic, str(payload))

    def send(self, device: str, value: str) -> bool:
        """Send one normalized command to the caller's own room node.

        Returns False if the command is invalid, the broker is unconfigured, or
        the caller has no single node to address. Every tenant reaches their own
        hardware and only their own: the topic is built from the caller's node,
        so there is nothing to get wrong at a call site.
        """
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

    def apply_actions(self, actions: List[Dict[str, str]]) -> Dict[str, Any]:
        """Send a list of [{device, value}]. Returns how many reached the broker.
        Refuses entirely (sent=[]) when the caller has no room node to address."""
        if not _caller_node_id():
            logger.warning("[room_device] apply_actions refused: no node for this caller")
            return {"available": self.available, "sent": [], "skipped": list(actions or [])}
        sent, skipped = [], []
        for a in actions or []:
            dev, val = a.get("device", ""), a.get("value", "")
            (sent if self.send(dev, val) else skipped).append({"device": dev, "value": val})
        return {"available": self.available, "sent": sent, "skipped": skipped}


_room_client: Optional[RoomDeviceClient] = None
_room_client_lock = threading.Lock()


def get_room_device_client() -> RoomDeviceClient:
    # Two request threads racing here each built a client — two broker
    # connections, one of them never used and never closed.
    global _room_client
    if _room_client is None:
        with _room_client_lock:
            if _room_client is None:
                _room_client = RoomDeviceClient()
    return _room_client
