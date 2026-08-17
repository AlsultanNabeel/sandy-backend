"""MQTT ingest — the backend's inbound listener for Sandy nodes.

Counterpart to room_device (which is publish-only). A single background subscriber
listens for what nodes report and updates the registry:

  sandy/node/<node_id>/status      -> node_store.ingest_status (heartbeat + caps)
  sandy/node/<node_id>/ir/learned  -> node_store.set_last_ir   (captured IR code)

Runs outside any tenant/request context, so it keys updates by node_id (which the
firmware derives from its code, matching node_store.code_to_node_id). Safe to start
unconditionally: it no-ops when MQTT isn't configured.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt  # type: ignore
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

_STATUS_SUB = "sandy/node/+/status"
_IR_SUB = "sandy/node/+/ir/learned"
# Photos come back split across many messages; camera_client holds the pieces.
_CAM_SUB = "sandy/node/+/cam/snapshot"
# نبضة الكاميرا. موضوع منفصل بمستويين لأنها لوح تاني بيشارك نفس معرّف الوحدة —
# الكاميرا جزء من ساندي، مش وحدة تانية. و`+` بتطابق مستوى واحد بس، فاشتراك
# الحالة العادي `sandy/node/+/status` **ما بيلتقطها أبدًا**.
#
# بدون هاد الاشتراك، الكاميرا بتبعت مخرجاتها لمكان ما حدا بيسمعه وما بتظهر
# بالتطبيق ولا مرّة — وهاد بالضبط اللي كان بيصير.
_CAM_STATUS_SUB = "sandy/node/+/cam/status"

_started = False
_lock = threading.Lock()
_client: Optional[Any] = None


def _node_id_from_topic(topic: str) -> str:
    # sandy/node/<node_id>/status  ->  <node_id>
    # sandy/node/<node_id>/ir/learned -> <node_id>
    parts = (topic or "").split("/")
    return parts[2] if len(parts) >= 3 else ""


def _on_message(client, userdata, msg) -> None:  # noqa: ANN001
    try:
        from app.features.node_store import ingest_status, set_last_ir

        node_id = _node_id_from_topic(msg.topic)
        if not node_id:
            return
        payload = msg.payload.decode("utf-8", "ignore").strip()

        if msg.topic.endswith("/ir/learned"):
            if payload:
                set_last_ir(node_id, payload)
            return

        if msg.topic.endswith("/cam/status"):
            _ingest_cam_status(node_id, payload)
            return

        if msg.topic.endswith("/cam/snapshot"):
            # Straight through, unparsed and unstored: a photo belongs to
            # whoever asked for it, and nobody may be waiting at all.
            from app.integrations.camera_client import on_chunk
            on_chunk(node_id, payload)
            return

        # status (retained JSON heartbeat)
        data = {}
        if payload:
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                data = {}
        ingest_status(
            node_id,
            online=bool(data.get("online", True)),
            capabilities=data.get("capabilities"),
            outputs=data.get("outputs"),
            firmware_version=str(data.get("firmware_version", "")),
            # The whole payload — node_store keeps only the fields it recognises.
            # Filtering there rather than here keeps the allowlist next to the
            # document it protects.
            telemetry=data,
        )
    except Exception as e:  # noqa: BLE001 — ingest must never crash the loop
        logger.debug("[mqtt_ingest] message handling failed: %s", e)


def _ingest_cam_status(node_id: str, payload: str) -> None:
    """The camera's heartbeat, merged into the node it shares an id with.

    The camera is part of Sandy, not a separate box: same pairing code, same
    node id, its own `cam/` branch of the topic tree. So its outputs have to be
    ADDED to whatever the brain declared, never written over them — two
    heartbeats arriving five seconds apart would otherwise take turns wiping
    each other out, and the app would flicker between a robot with a neck and a
    robot with a flash.

    Its outputs are namespaced `cam/...` for the same reason the topics are:
    both boards answer under one node id, and `flash` sitting beside `servo` in
    one list is a collision waiting for the day somebody adds a flash to the
    brain.
    """
    from app.features.node_store import get_node_any_tenant, ingest_status

    data = {}
    if payload:
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return

    cam_outputs = data.get("outputs")
    if not isinstance(cam_outputs, list):
        return

    namespaced = [
        {"id": f"cam/{o.get('id')}", "kind": o.get("kind")}
        for o in cam_outputs
        if isinstance(o, dict) and o.get("id")
    ]

    # Keep the brain's. A camera heartbeat says what the camera has; it says
    # nothing at all about the neck.
    existing = get_node_any_tenant(node_id) or {}
    kept = [o for o in (existing.get("outputs") or [])
            if isinstance(o, dict) and not str(o.get("id", "")).startswith("cam/")]

    ingest_status(
        node_id,
        online=True,
        capabilities=None,
        outputs=kept + namespaced,
        firmware_version="",
        # `cam_` مش `ip`.
        #
        # اللوحين بيشاركوا معرّف الوحدة، والتليمتري بتندمج بالمفتاح — فلوّ
        # الكاميرا بعتت `ip` كانت بتدهس عنوان الدماغ، وبعد خمس ثواني الدماغ
        # بيدهس عنوانها. الحقل الواحد كان بينقلب بين لوحين للأبد، وشاشة البثّ
        # بتوجّه ع الدماغ نص الوقت — والدماغ ما عنده `/stream`، فالبثّ بيفشل
        # مرّة من كل مرّتين بلا أي نمط يبيّن السبب.
        #
        # نفس درس المخارج بالضبط، بحقل تاني: لوحين تحت معرّف واحد لازم كل
        # واحد يكتب بمساحته.
        telemetry={f"cam_{k}": v for k, v in data.items()
                   if k in ("ip", "board")},
    )


def _on_connect(client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ANN001
    try:
        # QoS 0 for camera chunks on purpose: a photo is dozens of messages and
        # QoS 1 would double the round trips on a link the robot already shares
        # with live audio. A lost chunk means one retaken photo, not a lost one.
        client.subscribe([(_STATUS_SUB, 1), (_IR_SUB, 1),
                          (_CAM_SUB, 0), (_CAM_STATUS_SUB, 1)])
        logger.info("[mqtt_ingest] subscribed to node status + IR + camera")
    except Exception as e:  # noqa: BLE001
        logger.warning("[mqtt_ingest] subscribe failed: %s", e)


def start_mqtt_ingest() -> None:
    """Start the inbound subscriber once. No-op if MQTT isn't configured."""
    global _started, _client
    with _lock:
        if _started:
            return
        host = os.getenv("SANDY_MQTT_HOST", "").strip()
        user = os.getenv("SANDY_MQTT_USER", "").strip()
        password = os.getenv("SANDY_MQTT_PASS", "").strip()
        if not (MQTT_AVAILABLE and host and user and password):
            logger.info("[mqtt_ingest] not configured — inbound listener disabled")
            return
        try:
            port = int(os.getenv("SANDY_MQTT_PORT", "8883"))
        except ValueError:
            port = 8883
        try:
            c = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"sandy-ingest-{os.getpid()}",
                clean_session=True,
            )
            c.username_pw_set(user, password)
            c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
            c.on_connect = _on_connect
            c.on_message = _on_message
            c.connect(host, port, keepalive=60)
            c.loop_start()
            _client = c
            _started = True
            logger.info("[mqtt_ingest] started")
        except Exception as e:  # noqa: BLE001
            logger.warning("[mqtt_ingest] start failed: %s", e)
