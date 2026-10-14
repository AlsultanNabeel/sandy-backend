"""Inbound MQTT listener for Sandy nodes (device_publisher is publish-only).

  sandy/node/<id>/status       -> node_store.ingest_status (the robot's heartbeat)
  sandy/node/<id>/ir/learned   -> node_store.set_last_ir

Nothing else is subscribed: a camera or room board still flashed with old firmware
publishes under `cam/` and `room/`, which `+` never matches, so it is never heard.

Runs outside any tenant context, keyed by node_id. No-op when MQTT isn't configured.
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import ssl
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional

import paho.mqtt.client as mqtt  # type: ignore

logger = logging.getLogger(__name__)

MQTT_KEEPALIVE_S = 30

# Slow ingest (Atlas round trips) must not run on paho's network thread, or it
# misses keepalive pings and the broker drops us. One worker keeps messages in order.
_INGEST = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mqtt-ingest")


@atexit.register
def _drop_pending_ingest() -> None:
    """Drop queued work at exit so Heroku restarts don't hit R12 (exit timeout)."""
    _INGEST.shutdown(wait=False, cancel_futures=True)

# Bounded: heartbeats repeat, so dropping one is cheaper than running out of memory.
_INGEST_MAX_PENDING = 200

_STATUS_SUB = "sandy/node/+/status"
_IR_SUB = "sandy/node/+/ir/learned"

_started = False
_lock = threading.Lock()
_client: Optional[Any] = None

# Per-topic counters for /api/diagnose: "connected" can be true while a
# subscription was refused or the network thread is dead.
_stats = {
    "connects": 0,
    "disconnects": 0,
    "granted_qos": None,     # None until the broker answers SUBSCRIBE
    "status": 0,
    "ir": 0,
    "errors": 0,
    "dropped": 0,              # messages refused because the ingest queue was full
    "rebuilds": 0,
    "last_disconnect": None,   # why the broker last hung up — its words, not ours
    "last_disconnect_flags": None,
    "last_message_at": None,
}


def get_ingest_stats() -> dict:
    """This worker's listener stats, for /api/diagnose (per worker: they don't share memory)."""
    s = dict(_stats)
    s["pid"] = os.getpid()
    s["started"] = _started
    s["connected"] = bool(_client and _client.is_connected()) if _client else False
    return s


def _node_id_from_topic(topic: str) -> str:
    parts = (topic or "").split("/")
    return parts[2] if len(parts) >= 3 else ""


def _on_message(client, userdata, msg) -> None:  # noqa: ANN001
    """Runs on paho's network thread: copy the message and queue the work."""
    _stats["last_message_at"] = time.time()
    pending = _INGEST._work_queue.qsize()
    if pending >= _INGEST_MAX_PENDING:
        _stats["dropped"] += 1
        if _stats["dropped"] % 100 == 1:
            logger.warning("[mqtt_ingest] ingest queue full (%d) — dropping "
                           "messages; %d so far", pending, _stats["dropped"])
        return
    topic = str(msg.topic)
    payload = bytes(msg.payload or b"")
    try:
        _INGEST.submit(_handle_message, topic, payload, bool(getattr(msg, "retain", False)))
    except RuntimeError:      # pool shut down at exit
        logger.debug("[mqtt_ingest] ingest pool closed; message dropped")


def _handle_message(topic: str, raw: bytes, retained: bool = False) -> None:
    """One message. ``retained``: the broker's stored copy, handed over on (re)subscribing —
    every server restart gets each board's last heartbeat again, however old."""
    try:
        from app.features.node_store import ingest_status, set_last_ir

        node_id = _node_id_from_topic(topic)
        if not node_id:
            return
        payload = raw.decode("utf-8", "ignore").strip()

        if topic.endswith("/ir/learned"):
            _stats["ir"] += 1
            if payload:
                set_last_ir(node_id, payload)
            return

        # status (retained JSON heartbeat): the robot's own, one level under its id, never
        # an old camera's or room board's under a branch.
        if topic != f"sandy/node/{node_id}/status":
            return
        _stats["status"] += 1
        data = {}
        if payload:
            try:
                data = json.loads(payload)
            except (json.JSONDecodeError, ValueError):
                data = {}
        ingest_status(
            node_id,
            online=bool(data.get("online", True)),
            # A stored copy says nothing about when the board was last heard.
            heard=not retained,
            capabilities=data.get("capabilities"),
            outputs=data.get("outputs"),
            firmware_version=str(data.get("firmware_version", "")),
            telemetry=data,
        )
    except Exception as e:  # noqa: BLE001 — ingest must never crash the loop
        _stats["errors"] += 1
        logger.warning("[mqtt_ingest] %s failed: %s", topic, e)


def _on_connect(client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ANN001
    try:
        client.subscribe([(_STATUS_SUB, 1), (_IR_SUB, 1)])
        _stats["connects"] += 1
        logger.info("[mqtt_ingest] worker %d connected, subscribe sent "
                    "(rc=%s)", os.getpid(), reason_code)
    except Exception as e:  # noqa: BLE001
        logger.warning("[mqtt_ingest] subscribe failed: %s", e)


def _on_subscribe(client, userdata, mid, reason_codes, properties=None) -> None:  # noqa: ANN001
    """Log whether the broker granted each subscription (128 = refused).

    Must never raise: an exception can kill paho's network thread silently.
    """
    try:
        codes = [getattr(r, "value", r) for r in (reason_codes or [])]
        codes = [int(c) for c in codes]
    except Exception as e:  # noqa: BLE001
        logger.warning("[mqtt_ingest] could not read SUBACK: %s", e)
        _stats["granted_qos"] = "unreadable"
        return
    _stats["granted_qos"] = codes
    if any(c >= 128 for c in codes):
        logger.error(
            "[mqtt_ingest] worker %d: broker REFUSED a subscription %s "
            "(order: status, IR) — 128 means denied, "
            "usually a credential without permission on that topic",
            os.getpid(), codes)
    else:
        logger.info("[mqtt_ingest] worker %d granted %s", os.getpid(), codes)


def _on_disconnect(client, userdata, *args) -> None:  # noqa: ANN001
    """Record and log the broker's disconnect reason (e.g. 141 keepalive timeout, 142 session taken over).

    Arguments are identified by type, not position: paho's callback signature changes between versions.
    """
    _stats["disconnects"] += 1

    flags = reason = None
    for a in args:
        if a is None or isinstance(a, dict):
            continue
        if type(a).__name__ == "DisconnectFlags":
            flags = a
        elif isinstance(a, int) or hasattr(a, "getName") or hasattr(a, "value"):
            # int on the V1 signature, a ReasonCode object on V2.
            reason = a

    _stats["last_disconnect"] = str(reason)
    _stats["last_disconnect_flags"] = str(flags)

    # paho reports one drop twice; log it once.
    now = time.time()
    if now - _stats.get("last_disconnect_log", 0.0) < 1.0:
        return
    _stats["last_disconnect_log"] = now
    logger.warning(
        "[mqtt_ingest] worker %d disconnected: reason=%s flags=%s — paho will retry",
        os.getpid(), reason, flags)


def start_mqtt_ingest() -> None:
    """Start the inbound subscriber once. No-op if MQTT isn't configured."""
    global _started, _client
    with _lock:
        if _started:
            return
        host = os.getenv("SANDY_MQTT_HOST", "").strip()
        user = os.getenv("SANDY_MQTT_USER", "").strip()
        password = os.getenv("SANDY_MQTT_PASS", "").strip()
        if not (host and user and password):
            logger.info("[mqtt_ingest] not configured — inbound listener disabled")
            return
        try:
            port = int(os.getenv("SANDY_MQTT_PORT", "8883"))
        except ValueError:
            port = 8883
        try:
            c = _new_client(host, port, user, password)
            _client = c
            _started = True
            _stats["last_message_at"] = time.time()  # start the watchdog's clock
            logger.info("[mqtt_ingest] worker %d connecting to %s:%d",
                        os.getpid(), host, port)
            threading.Thread(target=_watchdog, args=(host, port, user, password),
                             name="mqtt-ingest-watchdog", daemon=True).start()
        except Exception as e:  # noqa: BLE001
            logger.warning("[mqtt_ingest] start failed: %s", e)


def _new_client(host: str, port: int, user: str, password: str):
    """Build a configured, connecting, looping subscriber (first start and watchdog rebuild)."""
    # Unique client id: pids repeat across dynos, and duplicate ids kick each other off the broker.
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
    c.on_subscribe = _on_subscribe
    c.reconnect_delay_set(min_delay=1, max_delay=30)

    # connect_async: a boot-time connect failure must not leave the worker deaf for life.
    # Short keepalive because the network thread competes for the GIL under load.
    c.connect_async(host, port, keepalive=MQTT_KEEPALIVE_S)
    c.loop_start()
    return c


# ── Watchdog ─────────────────────────────────────────────────────────────────
# Boards heartbeat every 5–10s, so silence is a fault. If paho's network thread
# dies, is_connected() stays True forever; rebuild the client instead.
_WATCHDOG_SILENCE_S = 90
_WATCHDOG_PERIOD_S = 30


def _watchdog(host: str, port: int, user: str, password: str) -> None:
    global _client
    while True:
        time.sleep(_WATCHDOG_PERIOD_S)
        try:
            c = _client
            last = _stats.get("last_message_at")
            if c is None or last is None:
                continue
            # A real message since the last rebuild ends the silent streak.
            if last > _stats.get("rebuilt_at", 0) + 1:
                _stats["silent_streak"] = 0
            streak = int(_stats.get("silent_streak", 0))
            silent_for = time.time() - last
            # Back off while no board is online at all.
            if silent_for < _WATCHDOG_SILENCE_S * (2 ** min(streak, 6)):
                continue

            (logger.error if streak == 0 else logger.warning)(
                "[mqtt_ingest] worker %d heard nothing for %.0fs (connected=%s) "
                "— rebuilding the listener",
                os.getpid(), silent_for, c.is_connected())

            # Rebuild, not reconnect: a dead network thread can't reconnect.
            try:
                c.loop_stop()
                c.disconnect()
            except Exception:  # noqa: BLE001
                pass

            _client = _new_client(host, port, user, password)
            now = time.time()
            _stats["last_message_at"] = now
            _stats["rebuilt_at"] = now
            _stats["silent_streak"] = streak + 1
            _stats["rebuilds"] = _stats.get("rebuilds", 0) + 1
        except Exception as e:  # noqa: BLE001 — the watchdog must outlive anything
            logger.warning("[mqtt_ingest] watchdog error: %s", e)
