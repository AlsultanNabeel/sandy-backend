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

try:
    from pymongo.errors import PyMongoError
except ImportError:  # pragma: no cover — pymongo is optional for this module
    # **This module must import without a database driver.**
    #
    # It is the camera path, not the storage layer: the topics, the chunk
    # assembly and the request logic are all testable — and were tested — with no
    # Mongo anywhere. A hard import turned "the inbox is unavailable" into "the
    # camera module cannot be loaded", which took the tests down with it.
    #
    # Named rather than broad on purpose: `except Exception` around a database
    # call hides bugs in the code that builds the query.
    class PyMongoError(Exception):
        pass

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

# Photos nobody in *this* process asked for. They are still somebody's photo.
#
# gunicorn runs two workers with separate memory, and the broker delivers every
# chunk to both. Only one holds the waiter, so the other used to drop its copy —
# which was correct until the copies started arriving late. Then the waiter timed
# out first, its slot was removed, and the complete photo was thrown away twice
# over: once by each worker, for two different reasons.
_unclaimed: Dict[str, _Pending] = {}
_MAX_UNCLAIMED = 8          # a handful of in-flight photos, not a cache

_lock = threading.Lock()

# ── The inbox ────────────────────────────────────────────────────────────────
#
# **A photo is saved when it arrives, not caught as it flies past.**
#
# Everything before this assumed the picture would land inside one fifteen-second
# window, in the one process that asked. Three separate things broke that
# assumption — a listener that reconnects, a board that answers in fourteen
# seconds when it is busy, and two workers that cannot see each other's memory —
# and each was fixed on its own while the shape stayed fragile: any future hiccup
# would look exactly the same again.
#
# So the chunks are assembled by whoever receives them and written here. The
# request reads from here. Now a slow board is slow, a dropped second is a
# delay, and the wrong worker is nothing at all — none of them are a lost photo.
_INBOX = "camera_inbox"
_INBOX_TTL_S = 120


def _inbox():
    from app.db import get_db
    db = get_db()
    return None if db is None else db[_INBOX]


def _inbox_put(node_id: str, req_id: str, jpeg: bytes) -> None:
    col = _inbox()
    if col is None:
        return
    try:
        col.replace_one(
            {"_id": f"{node_id}:{req_id}"},
            {"_id": f"{node_id}:{req_id}", "node_id": node_id, "req_id": req_id,
             "jpeg": jpeg, "at": time.time()},
            upsert=True)
        # Swept on write rather than by a timer: the only way photos accumulate
        # is by taking more of them, so the arrival of one is exactly when the
        # old ones stop being worth keeping.
        col.delete_many({"at": {"$lt": time.time() - _INBOX_TTL_S}})
    except PyMongoError as e:
        logger.warning("[camera] could not store photo %s: %s", req_id, e)


def _inbox_get(node_id: str, req_id: str) -> Optional[bytes]:
    col = _inbox()
    if col is None:
        return None
    try:
        doc = col.find_one({"_id": f"{node_id}:{req_id}"})
    except PyMongoError as e:
        logger.warning("[camera] could not read the inbox: %s", e)
        return None
    if not doc or time.time() - float(doc.get("at", 0)) > _INBOX_TTL_S:
        return None
    data = doc.get("jpeg")
    return bytes(data) if data else None


def _key(node_id: str, req_id: str) -> str:
    return f"{node_id}:{req_id}"


def _sweep() -> None:
    """Drop abandoned assemblies. Called on each new request rather than from a
    timer: the only way to accumulate them is to keep making requests."""
    now = time.monotonic()
    for k in [k for k, p in _pending.items()
              if now - p.started > _ASSEMBLY_TIMEOUT_S]:
        _pending.pop(k, None)
    # Unclaimed assemblies too: a photo that never finished arriving holds one of
    # only eight slots, and eight abandoned halves would lock out every real one.
    for k in [k for k, p in _unclaimed.items()
              if now - p.started > _ASSEMBLY_TIMEOUT_S]:
        _unclaimed.pop(k, None)


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

    key = _key(node_id, req_id)
    finished: Optional[bytes] = None

    with _lock:
        p = _pending.get(key)
        if p is None:
            # **Assemble it anyway.** No waiter here means the waiter is in the
            # other worker, or it gave up while the board was still talking.
            # Neither means nobody wants the photo — and dropping it was how a
            # complete, correct image got destroyed twice per capture.
            p = _unclaimed.get(key)
            if p is None:
                if len(_unclaimed) >= _MAX_UNCLAIMED:
                    return
                p = _Pending()
                _unclaimed[key] = p
                logger.info("[camera] worker %d assembling %s for whoever asked",
                            os.getpid(), req_id)

        if total > 0:
            p.total = total
        p.bytes_seen += len(blob)
        if p.bytes_seen > _MAX_IMAGE_BYTES or len(p.chunks) >= _MAX_CHUNKS:
            logger.warning("[camera] %s: oversized image, abandoning", node_id)
            p.event.set()
            _unclaimed.pop(key, None)
            return
        p.chunks[seq] = blob
        # سطر واحد بيقول إذا الدفعة وصلت كاملة ولا ناقصة.
        #
        # «ولا قطعة» و«سبعة من تسعة» عطلان مختلفان تمامًا: الأول اتصال، والتاني
        # ازدحام. وكانوا التنين بينطبعوا نفس الإشي — ولا إشي.
        if len(p.chunks) == 1 or (p.total and len(p.chunks) == p.total):
            logger.info("[camera] %s: %s — %d/%s chunks",
                        node_id, req_id, len(p.chunks), p.total or "?")
        if p.complete():
            p.event.set()
            _unclaimed.pop(key, None)
            # **Always stored, even when someone is waiting right here.**
            #
            # Storing only the unclaimed copies kept the old assumption alive in
            # a new place: that a local waiter means the photo is delivered. It
            # does not — the waiter can time out between the last chunk and the
            # assemble. The write costs one small round trip on a path that has
            # already spent seconds, and it makes the inbox the single answer to
            # "did this photo arrive", for every worker and every retry.
            finished = p.assemble()

    # Outside the lock: a database round trip must not hold up the MQTT loop,
    # which is delivering every other board's traffic too.
    if finished is not None:
        _inbox_put(node_id, req_id, finished)


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

    # **The first ask gets most of the clock, not half of it.**
    #
    # Splitting the budget evenly was a mistake that made things worse, and the
    # log showed it plainly: the board's answers were arriving at fourteen
    # seconds, so a seven-second first window guaranteed a miss, and the retry
    # then queued a second capture behind the first — which pushed the next
    # answer out further still. Each press made the board slower.
    #
    # A retry is only insurance against a lost burst. It must not be able to
    # turn a slow answer into a failed one, so it gets what is left over.
    first_s = timeout_s * 0.7
    jpeg, heard_anything = _attempt(node_id, first_s, settle_ms, flash)
    if jpeg is not None or heard_anything:
        return jpeg
    logger.info("[camera] %s: nothing heard in %.0fs — asking once more",
                node_id, first_s)
    return _attempt(node_id, timeout_s - first_s, settle_ms, flash)[0]


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

        # The fast path: the chunks landed in this process and the event fired.
        if p.event.wait(min(timeout_s, 3.0)) and p.complete():
            return p.assemble(), True

        # The patient path. The board may still be working, or the chunks may be
        # arriving in the other worker. Either way the photo ends up in the
        # inbox, so from here we just watch for it — which costs one small read
        # a second instead of a guess about who will get there first.
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if p.event.is_set() and p.complete():
                return p.assemble(), True
            found = _inbox_get(node_id, req_id)
            if found:
                logger.info("[camera] %s: %s arrived via the inbox (%d bytes)",
                            node_id, req_id, len(found))
                return found, True
            time.sleep(0.4)

        # **The evidence goes on the failure line itself.**
        #
        # This used to say `0/? chunks` and stop, which named the symptom and
        # nothing else. Answering "why" then meant a second tool, a login the
        # owner does not have, and another round trip — while the failure had
        # already happened and the numbers that explain it were sitting in memory
        # a function call away.
        #
        # Read it as: is this worker's listener connected, did the broker grant
        # all four subscriptions (128 = refused), and is it hearing heartbeats but
        # not chunks? Those are the causes, and this one line separates them
        # without asking anybody for anything.
        got, want = len(p.chunks), p.total or "?"
        # Read with .get() and no guard: `get_ingest_stats` copies a dict of
        # counters and asks the client whether it is connected. Wrapping that in
        # a catch would only be superstition, and a broad catch around code this
        # simple hides a typo in the very line meant to explain a failure.
        from app.integrations.mqtt_ingest import get_ingest_stats
        st = get_ingest_stats()
        silent = (f"{time.time() - st['last_message_at']:.0f}s"
                  if st.get("last_message_at") else "never")
        detail = (f"connected={st.get('connected')} granted={st.get('granted_qos')} "
                  f"status={st.get('status')} cam_status={st.get('cam_status')} "
                  f"cam_snapshot={st.get('cam_snapshot')} "
                  f"drops={st.get('disconnects')} errors={st.get('errors')} "
                  f"rebuilds={st.get('rebuilds', 0)} silent_for={silent}")
        logger.warning(
            "[camera] %s: worker %d gave up with %s/%s chunks and an empty "
            "inbox — ingest(%s)", node_id, os.getpid(), got, want, detail)
        return None, got > 0
    finally:
        with _lock:
            _pending.pop(_key(node_id, req_id), None)


def start_snapshot(node_id: str, settle_ms: int = 0,
                   flash: str = "auto") -> Optional[str]:
    """Ask for a photo and return immediately with a ticket.

    **Waiting was the whole problem.** A held request has to guess how long the
    board will take, and the board's answer moves: 1.3 seconds when it is idle,
    over twenty when it is not. Guess low and a photo that arrived perfectly is
    thrown away; guess high and a web request sits on a worker thread for half a
    minute — and this backend has sixteen of those in total, so a few people
    taking photos at once is an outage for everybody else.

    The ticket removes the guess. The board takes as long as it takes, whichever
    worker hears the chunks writes them to the inbox, and the caller comes back
    for them when it likes. Nothing has to happen inside one window any more.
    """
    node_id = (node_id or "").strip()
    if not node_id:
        return None
    req_id = uuid.uuid4().hex[:12]
    ok = _send(node_id, {
        "cmd": "snapshot",
        "id": req_id,
        "settle_ms": max(0, min(3000, int(settle_ms))),
        "flash": flash if flash in ("on", "off", "auto") else "auto",
    })
    if not ok:
        logger.info("[camera] %s: command not delivered", node_id)
        return None

    # **حالة السمع مع كل طلب.**
    #
    # كانت بتنطبع بسطر الفشل وقت ما الطلب كان بيستنّى الصورة. ولمّا صار يرجّع
    # تذكرة بعد تلات ثواني، ما عاد يوصل لهداك السطر — فاختفى التشخيص كله من
    # غير ما ينحذف. صار السجل يقول «طلب» وبعده صمت، وهاد بالضبط اللي كنّا
    # بنحاول نطلع منه.
    #
    # هون بينطبع مع كل التقاط: `cam_snapshot` بيعدّ يعني القطع بتوصل،
    # وثابت يعني ما بتوصل — والفرق بينهن هو كل التحقيق.
    try:
        from app.integrations.mqtt_ingest import get_ingest_stats
        st = get_ingest_stats()
        logger.info(
            "[camera] %s: asked (%s) — ingest(connected=%s status=%s "
            "cam_status=%s cam_snapshot=%s drops=%s last=%s)",
            node_id, req_id, st.get("connected"), st.get("status"),
            st.get("cam_status"), st.get("cam_snapshot"),
            st.get("disconnects"), st.get("last_disconnect"))
    except Exception as exc:  # noqa: BLE001 — التشخيص ما بيوقّف الالتقاط
        logger.debug("[camera] ingest stats unavailable: %s", exc)
    return req_id


def fetch_snapshot(node_id: str, req_id: str) -> Optional[bytes]:
    """The photo for a ticket, or None if it has not landed yet."""
    node_id, req_id = (node_id or "").strip(), (req_id or "").strip()
    if not node_id or not req_id:
        return None
    return _inbox_get(node_id, req_id)


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
