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
        )
    except Exception as e:  # noqa: BLE001 — ingest must never crash the loop
        logger.debug("[mqtt_ingest] message handling failed: %s", e)


def _on_connect(client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ANN001
    try:
        client.subscribe([(_STATUS_SUB, 1), (_IR_SUB, 1)])
        logger.info("[mqtt_ingest] subscribed to node status + IR")
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
