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
import uuid
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
                   if k in ("ip", "board", "ssid")},
    )


def _on_connect(client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ANN001
    try:
        # QoS 0 for camera chunks on purpose: a photo is dozens of messages and
        # QoS 1 would double the round trips on a link the robot already shares
        # with live audio. A lost chunk means one retaken photo, not a lost one.
        client.subscribe([(_STATUS_SUB, 1), (_IR_SUB, 1),
                          (_CAM_SUB, 0), (_CAM_STATUS_SUB, 1)])
        # The pid is in the line on purpose. gunicorn runs two workers and each
        # one has its own subscriber and its own memory — so "is ingest up?" is
        # not one question, it is one question per worker, and the answer used
        # to be invisible. Two of these lines at boot means both are listening.
        logger.info("[mqtt_ingest] worker %d subscribed (status, IR, camera)",
                    os.getpid())
    except Exception as e:  # noqa: BLE001
        logger.warning("[mqtt_ingest] subscribe failed: %s", e)


def _on_disconnect(client, userdata, *args) -> None:  # noqa: ANN001
    """A drop used to be silent, and silence read exactly like "working".

    Signature is loose because paho changed it between callback API versions and
    a TypeError raised inside a callback is swallowed by the network loop — the
    listener would then look connected while delivering nothing.
    """
    logger.warning("[mqtt_ingest] worker %d disconnected — paho will retry",
                   os.getpid())


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
            # **Unique per process, not per pid.**
            #
            # The id was `sandy-ingest-<pid>`. Containers each have their own pid
            # namespace, so gunicorn's workers get the same small numbers in every
            # dyno — and Heroku overlaps the new dyno with the old one on deploy.
            # Two live connections with one client id is a rule the broker settles
            # by kicking the older off, which reconnects and kicks the newer, for
            # as long as both exist. Heartbeats survive that (they repeat every
            # five seconds; one landing is enough). **A photo does not** — it is
            # seven messages in one burst, and a burst that arrives during a kick
            # is gone whole. That is the shape of `0/? chunks`.
            c = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"sandy-ingest-{os.getpid()}-{uuid.uuid4().hex[:8]}",
                clean_session=True,
            )
            c.username_pw_set(user, password)
            c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
            c.on_connect = _on_connect
            c.on_message = _on_message
            c.on_disconnect = _on_disconnect
            c.reconnect_delay_set(min_delay=1, max_delay=30)

            # **connect_async, not connect.**
            #
            # `connect()` resolves DNS and completes the TLS handshake inline, and
            # raised on failure — which we caught, warned about, and moved on from.
            # The worker then served traffic for the rest of its life with no
            # inbound listener at all. Nothing looked broken: the *other* worker's
            # ingest kept the registry fresh, so the robot showed online with a
            # current address, and only a request that needed an answer *back*
            # failed — and only when the load balancer happened to hand it to the
            # deaf worker. A photo that fails half the time, from a camera that
            # logs a clean capture, with no server error anywhere.
            #
            # Async hands the connect to the network thread, which retries on the
            # backoff above. A bad minute at boot costs a minute now, not the dyno.
            c.connect_async(host, port, keepalive=60)
            c.loop_start()
            _client = c
            _started = True
            logger.info("[mqtt_ingest] worker %d connecting to %s:%d",
                        os.getpid(), host, port)
        except Exception as e:  # noqa: BLE001
            logger.warning("[mqtt_ingest] start failed: %s", e)
