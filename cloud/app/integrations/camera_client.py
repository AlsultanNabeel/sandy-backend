"""Camera client — ask a robot's camera for a photo, and collect it.

The camera uploads a finished JPEG to ``/api/cam/upload`` in one signed HTTPS
request (see devices_api); this module sends the request for it and holds the
result until the caller comes back for it.

Topics, under the robot's own node namespace:

    sandy/node/<node_id>/cam/command    -> JSON: snapshot / flash / stream / set
    sandy/node/<node_id>/cam/event      <- JSON: uploaded / errors, per request id
    sandy/node/<node_id>/cam/status     <- heartbeat

**There is no photo-over-the-broker path any more.** The camera used to fall
back to splitting a failed upload into base64 chunks on ``cam/snapshot``. That
path carried no signature — anyone able to publish on a node's topics could
plant an image for a pending request — sent the home's pictures through a
third-party broker, and in practice delivered nothing: the pieces were lost
silently. The camera now retries the upload once and otherwise reports the
failure on ``cam/event``, which lands here as an error the app can show.

The camera board ships in the same box as the robot and is flashed with the same
pairing code, so it derives the same node_id. One robot is one node, and the
camera is more outputs on it — not a second thing the customer has to pair.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

try:
    from pymongo.errors import PyMongoError
except ImportError:  # pragma: no cover — pymongo is optional for this module
    # This module must import without a database driver: a hard import turned
    # "the inbox is unavailable" into "the camera module cannot be loaded".
    class PyMongoError(Exception):
        pass

logger = logging.getLogger(__name__)

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
             "jpeg": jpeg, "at": time.time(),
             # TTL-indexed (bootstrap.ensure_indexes): the sweep below only
             # runs when another photo arrives, so without this the last
             # picture taken in someone's home would stay forever.
             "expire_at": datetime.now(timezone.utc) + timedelta(seconds=_INBOX_TTL_S)},
            upsert=True)
        # Swept on write rather than by a timer: the only way photos accumulate
        # is by taking more of them, so the arrival of one is exactly when the
        # old ones stop being worth keeping.
        col.delete_many({"at": {"$lt": time.time() - _INBOX_TTL_S}})
    except PyMongoError as e:
        logger.warning("[camera] could not store photo %s: %s", req_id, e)


def _inbox_put_error(node_id: str, req_id: str, reason: str) -> None:
    """Record that a photo is not coming, so the caller stops waiting for it.

    Without this the camera's own "capture_failed" / "upload_failed" was logged
    and nothing else: the app polled for forty seconds and then said "no
    photo", the same words for a dead sensor, a broken upload and a camera that
    was never asked. The reason now reaches the person holding the phone.
    """
    col = _inbox()
    if col is None:
        return
    try:
        col.update_one(
            {"_id": f"{node_id}:{req_id}", "jpeg": {"$exists": False}},
            {"$set": {"node_id": node_id, "req_id": req_id,
                      "error": str(reason)[:40], "at": time.time(),
                      "expire_at": datetime.now(timezone.utc)
                      + timedelta(seconds=_INBOX_TTL_S)}},
            upsert=True)
    except PyMongoError as e:
        # A duplicate _id means the photo itself already landed — the photo wins.
        logger.debug("[camera] error not recorded for %s: %s", req_id, e)


def _inbox_get_error(node_id: str, req_id: str) -> Optional[str]:
    col = _inbox()
    if col is None:
        return None
    try:
        doc = col.find_one({"_id": f"{node_id}:{req_id}"}, {"error": 1, "at": 1})
    except PyMongoError:
        return None
    if not doc or time.time() - float(doc.get("at", 0)) > _INBOX_TTL_S:
        return None
    return doc.get("error") or None


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

    logger.info("[camera] %s: asked (%s)", node_id, req_id)
    return req_id


def store_snapshot(node_id: str, req_id: str, jpeg: bytes) -> None:
    """Put a finished photo where the waiting request will find it.

    Called by the upload endpoint: the image arrives whole in one HTTPS request
    or the upload fails loudly — there is nothing to reassemble.
    """
    _inbox_put((node_id or "").strip(), (req_id or "").strip(), jpeg)


def fetch_snapshot(node_id: str, req_id: str) -> Optional[bytes]:
    """The photo for a ticket, or None if it has not landed yet."""
    node_id, req_id = (node_id or "").strip(), (req_id or "").strip()
    if not node_id or not req_id:
        return None
    return _inbox_get(node_id, req_id)


# What the camera reports, and what the person holding the phone reads.
_ERROR_TEXT = {
    "camera_init_failed_at_boot": "الكاميرا ما اشتغلت من الإقلاع — افحص كبل الكاميرا والكهربا.",
    "capture_failed": "الكاميرا ما قدرت تصوّر. جرّب كمان مرّة.",
    "upload_failed": "الصورة انأخذت بس ما قدرت توصل للخادم. تأكد من شبكة الكاميرا.",
    "camera_busy": "الكاميرا مشغولة بلقطة تانية.",
}


def on_event(node_id: str, payload: str) -> None:
    """A ``cam/event`` message. Errors for a request become that request's answer."""
    try:
        data = json.loads(payload or "{}")
    except (json.JSONDecodeError, ValueError):
        return
    if not isinstance(data, dict):
        return
    req_id = str(data.get("id") or "").strip()
    reason = str(data.get("error") or "").strip()
    if not req_id or not reason or len(req_id) > 40:
        return
    _inbox_put_error((node_id or "").strip(), req_id, reason)


def fetch_snapshot_error(node_id: str, req_id: str) -> Optional[Dict[str, str]]:
    """``{"error": code, "message": text}`` if the camera said the photo is not
    coming, else None."""
    node_id, req_id = (node_id or "").strip(), (req_id or "").strip()
    if not node_id or not req_id:
        return None
    code = _inbox_get_error(node_id, req_id)
    if not code:
        return None
    return {"error": code,
            "message": _ERROR_TEXT.get(code, "الكاميرا ما قدرت تجيب الصورة.")}
