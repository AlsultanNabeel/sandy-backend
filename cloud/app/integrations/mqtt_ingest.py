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
import time
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

# قناة أحداث الكاميرا — «صوّرت، وهاد عدد القطع».
#
# ما كنّا نسمعها، وكانت هي الدليل الناقص: اللوح بينشر القطع (رسائل كبيرة) ثم
# حدث الاكتمال (رسالة صغيرة) **بنفس اللحظة وبنفس الاتصال**. فلو وصل الحدث
# وضاعت القطع، بيصير عندنا مقارنة مضبوطة — كل إشي متطابق إلا الحجم.
#
# وإلها فايدة دائمة بعد التشخيص: بتقول كم قطعة أرسل اللوح، فبنعرف «وصل ستّة من
# تسعة» بدل ما نستنّى ونخمّن.
_CAM_EVENT_SUB = "sandy/node/+/cam/event"

_started = False
_lock = threading.Lock()
_client: Optional[Any] = None

# ── What this listener has actually seen ─────────────────────────────────────
#
# Added because a whole class of question was unanswerable from outside: the
# camera's own log showed a clean capture and five chunks published, the broker
# demonstrably fanned them out (the board is subscribed to its own branch and
# received them back), and the server said `0/? chunks`. Every layer reported
# success and the photo was gone.
#
# The gap was that "is the server's subscriber alive and receiving?" had no
# answer anywhere. Publishing works through a *different* client, so a flash
# returning 200 proves nothing about this one. And heartbeats are forgiving —
# they repeat every five seconds, so the registry looks fresh even if most of
# them are lost, which makes a half-dead subscriber invisible.
#
# Counters, not a health flag: "connected" can be true while a subscription was
# refused. A count that stays at zero while another climbs is the difference
# between "the link is down" and "this one topic never arrives" — and those have
# nothing in common as bugs.
_stats = {
    "connects": 0,
    "disconnects": 0,
    "granted_qos": None,     # None until the broker answers SUBSCRIBE
    "status": 0,
    "ir": 0,
    "cam_status": 0,
    "cam_snapshot": 0,
    "cam_event": 0,
    "errors": 0,
    "rebuilds": 0,
    "last_disconnect": None,   # why the broker last hung up — its words, not ours
    "last_message_at": None,
}


def get_ingest_stats() -> dict:
    """A snapshot of this worker's listener, for /api/diagnose.

    Per worker on purpose — gunicorn runs two and they do not share memory, so a
    single global number would average away exactly the asymmetry worth seeing.
    """
    s = dict(_stats)
    s["pid"] = os.getpid()
    s["started"] = _started
    s["connected"] = bool(_client and _client.is_connected()) if _client else False
    return s


def _node_id_from_topic(topic: str) -> str:
    # sandy/node/<node_id>/status  ->  <node_id>
    # sandy/node/<node_id>/ir/learned -> <node_id>
    parts = (topic or "").split("/")
    return parts[2] if len(parts) >= 3 else ""


def _on_message(client, userdata, msg) -> None:  # noqa: ANN001
    _stats["last_message_at"] = time.time()
    try:
        from app.features.node_store import ingest_status, set_last_ir

        node_id = _node_id_from_topic(msg.topic)
        if not node_id:
            return
        payload = msg.payload.decode("utf-8", "ignore").strip()

        if msg.topic.endswith("/ir/learned"):
            _stats["ir"] += 1
            if payload:
                set_last_ir(node_id, payload)
            return

        if msg.topic.endswith("/cam/status"):
            _stats["cam_status"] += 1
            _ingest_cam_status(node_id, payload)
            return

        if msg.topic.endswith("/cam/event"):
            # صغيرة، ومن نفس اللوح، وبنفس ثانية القطع. لو وصلت هي وضاعت هنّ،
            # الحجم هو الفرق الوحيد الباقي.
            _stats["cam_event"] += 1
            logger.info("[camera] %s event: %s", node_id, payload[:160])
            return

        if msg.topic.endswith("/cam/snapshot"):
            _stats["cam_snapshot"] += 1
            # Straight through, unparsed and unstored: a photo belongs to
            # whoever asked for it, and nobody may be waiting at all.
            from app.integrations.camera_client import on_chunk
            on_chunk(node_id, payload)
            return

        # status (retained JSON heartbeat)
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
            capabilities=data.get("capabilities"),
            outputs=data.get("outputs"),
            firmware_version=str(data.get("firmware_version", "")),
            # The whole payload — node_store keeps only the fields it recognises.
            # Filtering there rather than here keeps the allowlist next to the
            # document it protects.
            telemetry=data,
        )
    except Exception as e:  # noqa: BLE001 — ingest must never crash the loop
        # Was DEBUG, which on a quiet log level is the same as not logging. A
        # handler that throws on every message looks exactly like a handler that
        # is never called, and the two were confused for days.
        _stats["errors"] += 1
        logger.warning("[mqtt_ingest] %s failed: %s", getattr(msg, "topic", "?"), e)


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
        # `boot` = سبب آخر إقلاع للكاميرا، جايي من اللوح نفسه.
        #
        # «بتعمل ريستارت» كانت بتحتاج كبل وحظّ — لازم تكون شابك ومتفرّج بالثانية
        # اللي صارت فيها. هيك بتوصل بالنبضة، وبتنقرا من التطبيق بعدها بساعة.
        telemetry={f"cam_{k}": v for k, v in data.items()
                   if k in ("ip", "board", "ssid", "boot")},
    )


def _on_connect(client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ANN001
    try:
        # QoS 0 for camera chunks on purpose: a photo is dozens of messages and
        # QoS 1 would double the round trips on a link the robot already shares
        # with live audio. A lost chunk means one retaken photo, not a lost one.
        client.subscribe([(_STATUS_SUB, 1), (_IR_SUB, 1),
                          (_CAM_SUB, 1), (_CAM_STATUS_SUB, 1),
                          (_CAM_EVENT_SUB, 1)])
        _stats["connects"] += 1
        # The pid is in the line on purpose. gunicorn runs two workers and each
        # one has its own subscriber and its own memory — so "is ingest up?" is
        # not one question, it is one question per worker, and the answer used
        # to be invisible. Two of these lines at boot means both are listening.
        logger.info("[mqtt_ingest] worker %d connected, subscribe sent "
                    "(rc=%s)", os.getpid(), reason_code)
    except Exception as e:  # noqa: BLE001
        logger.warning("[mqtt_ingest] subscribe failed: %s", e)


def _on_subscribe(client, userdata, mid, reason_codes, properties=None) -> None:  # noqa: ANN001
    """**Whether the broker actually granted the subscription.**

    `client.subscribe()` returns as soon as the packet is written. The answer
    comes back separately, and a refusal is `128` — per topic, so three can
    succeed and the fourth be denied with nothing anywhere to say so. We never
    looked, which left "we are subscribed" as an assumption in the one place the
    whole camera path depends on it.
    """
    # **Nothing in here may raise.** paho runs callbacks on the network thread,
    # and an exception escaping one can take that thread down — after which the
    # client still reports `connected=True`, still fires no disconnect, and
    # simply never delivers another message. That failure is invisible from
    # every angle except a message counter stuck at zero.
    #
    # `reason_codes` is a list of ReasonCode objects here, not ints, and calling
    # int() on one is exactly the kind of small assumption that kills a thread.
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
            "(order: status, IR, cam/snapshot, cam/status) — 128 means denied, "
            "usually a credential without permission on that topic",
            os.getpid(), codes)
    else:
        logger.info("[mqtt_ingest] worker %d granted %s", os.getpid(), codes)


def _on_disconnect(client, userdata, *args) -> None:  # noqa: ANN001
    """A drop used to be silent, and silence read exactly like "working".

    Signature is loose because paho changed it between callback API versions and
    a TypeError raised inside a callback is swallowed by the network loop — the
    listener would then look connected while delivering nothing.

    **And it logs the reason.** It used to say only "disconnected", which meant
    a week of guessing at a link that drops on a regular fifteen-second cycle —
    a rhythm too even to be a bad network. The broker states the cause in the
    packet and it was being thrown away:

        142 (0x8E)  session taken over — another client connected with this id
        141 (0x8D)  keep alive timeout — our pings stopped arriving
        139 (0x8B)  server shutting down
        152 (0x98)  maximum connect time / quota

    Each one has a different fix and no two look alike. Reading it is the
    difference between knowing and theorising.
    """
    _stats["disconnects"] += 1
    reason = next((a for a in args if a is not None
                   and not isinstance(a, dict)), None)
    _stats["last_disconnect"] = str(reason)
    logger.warning("[mqtt_ingest] worker %d disconnected: %s — paho will retry",
                   os.getpid(), reason)


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
            c.on_subscribe = _on_subscribe
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
            _stats["last_message_at"] = time.time()  # start the watchdog's clock
            logger.info("[mqtt_ingest] worker %d connecting to %s:%d",
                        os.getpid(), host, port)
            threading.Thread(target=_watchdog, args=(host, port, user, password),
                             name="mqtt-ingest-watchdog", daemon=True).start()
        except Exception as e:  # noqa: BLE001
            logger.warning("[mqtt_ingest] start failed: %s", e)


# ── Watchdog ─────────────────────────────────────────────────────────────────
#
# The robot heartbeats every five seconds and the camera every ten. **Silence is
# therefore not ambiguous here** — it is not a quiet period, it is a fault. That
# makes a watchdog trivial to get right, and it covers a class of failure rather
# than one cause.
#
# It exists because of a failure that reported itself as healthy from every
# angle: `connected=True`, no disconnect, no error, and zero messages received in
# four minutes. paho sets the connected flag on CONNACK and clears it in the
# network loop — so if that thread dies, the flag stays true forever and the
# client lies politely for the life of the dyno. Requests routed to that worker
# waited fifteen seconds for an answer that could not arrive.
#
# Ninety seconds is eighteen missed heartbeats. Nothing survivable looks like
# that, and nothing healthy does either.
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
            silent_for = time.time() - last
            if silent_for < _WATCHDOG_SILENCE_S:
                continue

            logger.error(
                "[mqtt_ingest] worker %d heard nothing for %.0fs (connected=%s) "
                "— rebuilding the listener",
                os.getpid(), silent_for, c.is_connected())

            # Rebuilt, not reconnected. If the network thread is gone, there is
            # nothing left to ask to try again — `reconnect()` would be handed to
            # a corpse and return without error, which is how this hid for so
            # long. A fresh client brings a fresh thread.
            try:
                c.loop_stop()
                c.disconnect()
            except Exception:  # noqa: BLE001 — it is already broken
                pass

            n = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2,
                client_id=f"sandy-ingest-{os.getpid()}-{uuid.uuid4().hex[:8]}",
                clean_session=True,
            )
            n.username_pw_set(user, password)
            n.tls_set(cert_reqs=ssl.CERT_REQUIRED)
            n.on_connect = _on_connect
            n.on_message = _on_message
            n.on_disconnect = _on_disconnect
            n.on_subscribe = _on_subscribe
            n.reconnect_delay_set(min_delay=1, max_delay=30)
            n.connect_async(host, port, keepalive=60)
            n.loop_start()
            _client = n
            _stats["last_message_at"] = time.time()
            _stats["rebuilds"] = _stats.get("rebuilds", 0) + 1
        except Exception as e:  # noqa: BLE001 — the watchdog must outlive anything
            logger.warning("[mqtt_ingest] watchdog error: %s", e)
