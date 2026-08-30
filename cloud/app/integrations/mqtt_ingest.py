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

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt  # type: ignore
    MQTT_AVAILABLE = True
except ImportError:
    MQTT_AVAILABLE = False

# See the note at connect_async: the listener does not have a thread to itself.
MQTT_KEEPALIVE_S = 30

# **Nothing slow runs on paho's network thread.**
#
# `_on_message` used to do the whole ingest inline: parse the heartbeat, then
# `ingest_status`, which is several Atlas round trips. That thread has one other
# job — sending PINGREQ before the keepalive expires — and it cannot do it while
# it is waiting on a database in Virginia. The broker sees a client that stopped
# pinging and drops it:
#
#     [mqtt_ingest] worker 12 disconnected: reason=Keep alive timeout
#     [mqtt_ingest] worker 12 connected, subscribe sent
#
# every seventy seconds, on both workers, forever. It filled the log to the point
# where an actual conversation could not be found in it, and every drop is a
# window where a command to the robot goes nowhere.
#
# One worker, not the shared pool: heartbeats and photo chunks arrive in an order
# that means something, and a pool of eight would write an older state over a
# newer one and hand the camera its slices shuffled.
_INGEST = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mqtt-ingest")


@atexit.register
def _drop_pending_ingest() -> None:
    """Let the dyno die on time.

    `concurrent.futures` joins its worker threads at interpreter exit, and this
    one can be sitting on a Mongo call with a queue behind it — so a restart hit
    `Error R12 (Exit timeout)` and Heroku killed the process with SIGKILL after
    thirty seconds. Registered after that module's own hook, so it runs before
    it: the queue is thrown away and only the job already in flight is waited
    on. Nothing here is worth delaying a deploy for — every message is a
    heartbeat that will be sent again.
    """
    _INGEST.shutdown(wait=False, cancel_futures=True)

# A bound, because an unbounded queue in front of a stalled database is just a
# slower way to run out of memory. Heartbeats are retained and repeat every few
# seconds, so dropping one costs nothing; the alternative costs the dyno.
_INGEST_MAX_PENDING = 200

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

# نبضة عقدة الغرفة — نفس القصة تمامًا، لوح تالت تحت نفس معرّف الوحدة.
#
# وبدونها العقدة شغّالة وغير موجودة: بتتصل، وبتنفّذ الأوامر، وما بتظهر
# بالتطبيق ولا مرّة — لأن اللي بيسجّل جهازًا هو **إعلان اللوح عن مخارجه**،
# وما كان في حدا يسمع الإعلان.
_ROOM_STATUS_SUB = "sandy/node/+/room/status"

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
    "room_status": 0,
    "errors": 0,
    "rebuilds": 0,
    "last_disconnect": None,   # why the broker last hung up — its words, not ours
    "last_disconnect_flags": None,
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
    """Hand off and return. **This runs on paho's network thread.**

    Everything this function does before returning is time the client is not
    sending its keepalive ping, so it copies the two values it needs off the
    message and queues the work. See `_INGEST`.
    """
    _stats["last_message_at"] = time.time()
    pending = _INGEST._work_queue.qsize()
    if pending >= _INGEST_MAX_PENDING:
        _stats["dropped"] = _stats.get("dropped", 0) + 1
        if _stats["dropped"] % 100 == 1:
            logger.warning("[mqtt_ingest] ingest queue full (%d) — dropping "
                           "messages; %d so far", pending, _stats["dropped"])
        return
    topic = str(msg.topic)
    payload = bytes(msg.payload or b"")
    try:
        _INGEST.submit(_handle_message, topic, payload)
    except RuntimeError:      # pool shut down at exit
        logger.debug("[mqtt_ingest] ingest pool closed; message dropped")


def _handle_message(topic: str, raw: bytes) -> None:
    """The actual ingest, on our own thread where it can take as long as it takes."""
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

        if topic.endswith("/cam/status"):
            _stats["cam_status"] += 1
            _ingest_cam_status(node_id, payload)
            return

        if topic.endswith("/room/status"):
            _stats["room_status"] += 1
            _ingest_room_status(node_id, payload)
            return

        if topic.endswith("/cam/event"):
            # صغيرة، ومن نفس اللوح، وبنفس ثانية القطع. لو وصلت هي وضاعت هنّ،
            # الحجم هو الفرق الوحيد الباقي.
            _stats["cam_event"] += 1
            logger.info("[camera] %s event: %s", node_id, payload[:160])
            return

        if topic.endswith("/cam/snapshot"):
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
        logger.warning("[mqtt_ingest] %s failed: %s", topic, e)


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
    from app.features.node_store import ingest_status

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

    # Only the camera's own. Keeping the brain's is node_store._merge_outputs's
    # job, by namespace — this used to re-read them and pass them back in, which
    # meant the merge ran twice over the same list and every brain output came
    # back doubled.
    ingest_status(
        node_id,
        online=True,
        capabilities=None,
        outputs=namespaced,
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


def _ingest_room_status(node_id: str, payload: str) -> None:
    """The room node's heartbeat, merged into the node it shares an id with.

    Same shape as the camera's, for the same reason: a third board under one
    pairing code, writing in its own ``room/`` prefix so its lamp never collides
    with anything the brain declares.

    **This is what puts the room in the app.** A device exists because a board
    said it exists — the catalogue only decides how to draw it. Before this, the
    room node worked perfectly and was invisible: it connected, it obeyed
    commands published by hand, and the app's "add device" screen could not offer
    a lamp because nothing had ever declared one. The owner would have had to
    describe his own hardware to the app, which is the thing provisioning exists
    to prevent.
    """
    from app.features.node_store import ingest_status

    data = {}
    if payload:
        try:
            data = json.loads(payload)
        except (json.JSONDecodeError, ValueError):
            return

    room_outputs = data.get("outputs")
    if not isinstance(room_outputs, list):
        return

    namespaced = [
        {"id": f"room/{o.get('id')}", "kind": o.get("kind")}
        for o in room_outputs
        if isinstance(o, dict) and o.get("id")
    ]

    ingest_status(
        node_id,
        online=True,
        capabilities=None,
        outputs=namespaced,
        firmware_version="",
        # `room_` مثل `cam_` بالضبط: التليمتري بتندمج بالمفتاح، ولوّ العقدة
        # بعتت `ip` كانت بتدهس عنوان الدماغ وبالعكس كل خمس ثواني.
        telemetry={f"room_{k}": v for k, v in data.items()
                   if k in ("ip", "board", "light", "rssi")},
    )


def _on_connect(client, userdata, flags, reason_code, properties=None) -> None:  # noqa: ANN001
    try:
        # QoS 0 for camera chunks on purpose: a photo is dozens of messages and
        # QoS 1 would double the round trips on a link the robot already shares
        # with live audio. A lost chunk means one retaken photo, not a lost one.
        client.subscribe([(_STATUS_SUB, 1), (_IR_SUB, 1),
                          (_CAM_SUB, 1), (_CAM_STATUS_SUB, 1),
                          (_CAM_EVENT_SUB, 1), (_ROOM_STATUS_SUB, 1)])
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

    **And for a while it still was not reading it.** The line above took the
    first non-dict argument, and in paho's V2 signature —
    ``(client, userdata, disconnect_flags, reason_code, properties)`` — the first
    non-dict argument is the *flags*. So every drop logged
    ``DisconnectFlags(is_disconnect_packet_from_server=False)``: true, useless,
    and identical whatever the cause. The reason code was sitting in the next
    argument, discarded, for as long as this docstring claimed otherwise.

    Positional guessing is what broke it, so the arguments are now identified by
    what they are rather than by where they sit — paho has changed this signature
    once already and will not ask before doing it again.
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

    # paho reports one drop twice — once from the socket close and once from the
    # loop unwinding — so every disconnect appeared in the log as an identical
    # pair with the same timestamp. Two lines for one event reads as two events,
    # which doubles the apparent rate of the very problem you are measuring.
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
            # **Thirty seconds, not sixty.**
            #
            # The listener shares a gunicorn worker with request handling and
            # with a live voice WebSocket that streams audio for minutes. paho's
            # network thread has to be scheduled to send its PINGREQ, and under
            # that load it may not be — a keepalive the broker measures in wall
            # clock is being kept by a thread competing for the GIL. Pinging
            # twice as often halves the window in which a busy stretch looks to
            # the broker like a dead client, and costs two packets a minute.
            c.connect_async(host, port, keepalive=MQTT_KEEPALIVE_S)
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
            n.connect_async(host, port, keepalive=MQTT_KEEPALIVE_S)
            n.loop_start()
            _client = n
            _stats["last_message_at"] = time.time()
            _stats["rebuilds"] = _stats.get("rebuilds", 0) + 1
        except Exception as e:  # noqa: BLE001 — the watchdog must outlive anything
            logger.warning("[mqtt_ingest] watchdog error: %s", e)
