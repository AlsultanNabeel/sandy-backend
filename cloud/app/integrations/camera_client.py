"""Camera client — request a photo from a robot's camera board and get it back.

The camera has been the most finished part of the hardware and the least reachable
part of the product: fully flashed and verified on the bench, with nothing in this
backend able to ask it for anything. This is that missing half.

Why it needs a module of its own rather than a row in the device registry: every
other control is fire-and-forget — publish "on", done. A photo is a request that
expects an answer, and the answer does not fit in one MQTT message. The board
splits a JPEG across many base64 chunks, so something has to hold the pieces,
notice when they are all in, and hand back one image — while a completely
different thread does the waiting.

Topics, under the robot's own node namespace:

    sandy/node/<node_id>/cam/command    -> JSON: snapshot / flash / stream / set
    sandy/node/<node_id>/cam/snapshot   <- JSON chunks: {id, seq, total, data}
    sandy/node/<node_id>/cam/status     <- current settings

The camera board ships in the same box as the robot and is flashed with the same
pairing code, so it derives the same node_id. One robot is one node, and the
camera is more outputs on it — not a second thing the customer has to pair.

Ownership is not checked here. It is checked once, at the actuation boundary in
room_device.send_to_topic, against the calling tenant's own registry — so a
tenant can only ever address a camera on a node they paired.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# A photo that has not finished arriving within this long is not coming.
_ASSEMBLY_TIMEOUT_S = 30.0
# A JPEG from this sensor is tens of KB. The cap is here so a malformed or
# hostile stream of chunks cannot grow a buffer without bound — the ingest
# thread is fed by a shared broker.
_MAX_IMAGE_BYTES = 512 * 1024
_MAX_CHUNKS = 512


class _Pending:
    __slots__ = ("chunks", "total", "event", "started", "bytes_seen")

    def __init__(self) -> None:
        self.chunks: Dict[int, bytes] = {}
        self.total = 0
        self.event = threading.Event()
        self.started = time.monotonic()
        self.bytes_seen = 0

    def complete(self) -> bool:
        return self.total > 0 and len(self.chunks) >= self.total

    def assemble(self) -> bytes:
        return b"".join(self.chunks[i] for i in sorted(self.chunks))


_pending: Dict[str, _Pending] = {}
_lock = threading.Lock()


def _key(node_id: str, req_id: str) -> str:
    return f"{node_id}:{req_id}"


def _sweep() -> None:
    """Drop abandoned assemblies. Called on each new request rather than from a
    timer: the only way to accumulate them is to keep making requests."""
    now = time.monotonic()
    for k in [k for k, p in _pending.items()
              if now - p.started > _ASSEMBLY_TIMEOUT_S]:
        _pending.pop(k, None)


def on_chunk(node_id: str, payload: str) -> None:
    """Feed one chunk from the ingest thread. Never raises — a bad payload must
    not take the MQTT loop down with it."""
    try:
        data = json.loads(payload)
        req_id = str(data.get("id", "")).strip()
        seq = int(data.get("seq", 0))
        total = int(data.get("total", 0))
        b64 = data.get("data", "")
        if not req_id or not b64 or seq < 0 or seq >= _MAX_CHUNKS:
            return
        blob = base64.b64decode(b64)
    except Exception as e:  # noqa: BLE001
        logger.debug("[camera] bad chunk: %s", e)
        return

    with _lock:
        p = _pending.get(_key(node_id, req_id))
        # No waiter means a late chunk from a request that already timed out, or
        # a board talking to a backend that never asked. Dropping it is correct:
        # buffering photos nobody is waiting for is how a memory leak starts.
        #
        # **But say so.** Dropping silently made two very different failures
        # print the same line — `0/? chunks` covered both "the broker never
        # delivered anything" and "it delivered to the other gunicorn worker,
        # which was not the one waiting". Those need opposite fixes, and a week
        # went into guessing which. One log line separates them for good.
        if p is None:
            if seq == 0:
                logger.info(
                    "[camera] worker %d got chunk 0 of %s with nobody waiting "
                    "— the request is on another worker, or it already timed out",
                    os.getpid(), req_id)
            return
        if total > 0:
            p.total = total
        p.bytes_seen += len(blob)
        if p.bytes_seen > _MAX_IMAGE_BYTES or len(p.chunks) >= _MAX_CHUNKS:
            logger.warning("[camera] %s: oversized image, abandoning", node_id)
            p.event.set()
            return
        p.chunks[seq] = blob
        if p.complete():
            p.event.set()


def _send(node_id: str, command: Dict[str, Any]) -> bool:
    """Publish on the camera's command channel.

    `send_to_topic` is not usable here and the reason is worth stating, because
    the symptom was maddening: it authorises by finding a DEVICE whose transport
    produces the topic, and `cam/command` is not a device. It is the camera's
    service channel — the same one snapshots and bursts have always used. So
    every publish was refused, and "take a photo" reported that the camera might
    be off or the command had not arrived. The command had never left the server.

    Ownership is still enforced, on the thing that actually has an owner: the
    node. A tenant-scoped lookup means another tenant's camera is simply not
    found, which is the same guarantee by a more honest route.
    """
    from app.features.node_store import get_node
    from app.integrations.room_device import get_room_device_client

    node_id = (node_id or "").strip()
    if not node_id or get_node(node_id) is None:
        logger.warning("[camera] refused: %s is not a node this caller owns", node_id)
        return False

    topic = f"sandy/node/{node_id}/cam/command"
    try:
        return get_room_device_client().publish_service(topic, json.dumps(command))
    except Exception as e:  # noqa: BLE001
        logger.warning("[camera] publish failed: %s", e)
        return False


def request_snapshot(node_id: str, timeout_s: float = 15.0,
                     settle_ms: int = 0, flash: str = "auto") -> Optional[bytes]:
    """Ask for one photo and wait for it. Returns JPEG bytes, or None.

    ``settle_ms`` is a pause before the shutter, for when the neck has just moved
    and the image is still stabilising — the camera firmware honours it, and it is
    the difference between a panorama and a row of blurred frames.

    **Asks twice if the first attempt hears absolutely nothing**, and the reason
    is a property of the link we cannot fix from either end:

    The board publishes at QoS 0 — PubSubClient has no other mode — so the broker
    will not hold those messages for a subscriber that is briefly away. Our
    listener does go away: it drops and reconnects within a second, repeatedly.
    Almost nothing notices, because almost everything here repeats. Heartbeats
    arrive every five seconds, so losing one costs nothing at all.

    A photo is the exception, and it is the *only* exception in the system: five
    to seven messages emitted in one burst, once. A burst that lands in a
    one-second gap is not degraded, it is **gone** — and the board logs a perfect
    capture, because from its side the capture *was* perfect. That asymmetry is
    why this failed every time while everything around it looked healthy.

    So: nothing heard at all means we asked into a gap, and asking again is
    correct. **Partial** chunks mean the link was up and something else went
    wrong — retrying then would only race a second capture against the first, so
    we let the original attempt use the whole budget instead.
    """
    node_id = (node_id or "").strip()
    if not node_id:
        return None

    jpeg, heard_anything = _attempt(node_id, timeout_s / 2, settle_ms, flash)
    if jpeg is not None or heard_anything:
        return jpeg
    logger.info("[camera] %s: nothing heard on the first ask — asking once more",
                node_id)
    return _attempt(node_id, timeout_s / 2, settle_ms, flash)[0]


def _attempt(node_id: str, timeout_s: float, settle_ms: int,
             flash: str) -> tuple[Optional[bytes], bool]:
    """One ask. Returns (jpeg or None, whether any chunk at all arrived).

    The second value is returned rather than stored on the module because two
    people can ask for a photo at the same moment, and a shared flag would let
    one caller's silence cancel the other's retry — a bug that would appear only
    under the load nobody reproduces locally.
    """
    req_id = uuid.uuid4().hex[:12]
    p = _Pending()
    with _lock:
        _sweep()
        _pending[_key(node_id, req_id)] = p

    try:
        ok = _send(node_id, {
            "cmd": "snapshot",
            "id": req_id,
            "settle_ms": max(0, min(3000, int(settle_ms))),
            "flash": flash if flash in ("on", "off", "auto") else "auto",
        })
        if not ok:
            # Not worth a second ask: the command never left the server, so the
            # camera is not the thing that failed and asking again will not
            # change it.
            logger.info("[camera] %s: command not delivered", node_id)
            return None, True

        if not p.event.wait(timeout_s):
            got, want = len(p.chunks), p.total or "?"
            # **The evidence goes on the failure line itself.**
            #
            # This used to say `0/? chunks` and stop, which named the symptom and
            # nothing else. Answering "why" then meant a second tool, a login the
            # owner does not have, and another round trip — while the failure had
            # already happened and the numbers that explain it were sitting in
            # memory a function call away.
            #
            # Read it as: is this worker's listener connected, did the broker
            # grant all four subscriptions (128 = refused), and is it hearing
            # heartbeats but not chunks? Those are the three causes, and this one
            # line separates them without asking anybody for anything.
            try:
                from app.integrations.mqtt_ingest import get_ingest_stats
                st = get_ingest_stats()
                detail = (f"connected={st['connected']} granted={st['granted_qos']} "
                          f"status={st['status']} cam_status={st['cam_status']} "
                          f"cam_snapshot={st['cam_snapshot']} "
                          f"drops={st['disconnects']} errors={st['errors']}")
            except Exception as e:  # noqa: BLE001 — diagnosis must not mask the failure
                detail = f"ingest stats unavailable: {e}"
            logger.warning(
                "[camera] %s: worker %d timed out with %s/%s chunks — ingest(%s)",
                node_id, os.getpid(), got, want, detail)
            return None, got > 0
        if not p.complete():
            return None, len(p.chunks) > 0
        return p.assemble(), True
    finally:
        with _lock:
            _pending.pop(_key(node_id, req_id), None)


def set_flash(node_id: str, state: str, level: int = 128) -> bool:
    """Torch on/off — separate from the shutter flash, for lighting a dark room."""
    if state not in ("on", "off"):
        return False
    return _send(node_id, {"cmd": "flash", "state": state,
                           "level": max(0, min(255, int(level)))})


def set_stream(node_id: str, on: bool) -> bool:
    """Start or stop the board's HTTP video server. The URL comes back on the
    camera's status topic — this only asks."""
    return _send(node_id, {"cmd": "stream", "state": "on" if on else "off"})
