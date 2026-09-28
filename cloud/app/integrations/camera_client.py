"""Ask a robot's camera for a photo, and collect it.

The camera uploads the JPEG to /api/cam/upload (signed HTTPS); errors arrive on
cam/event. Topics: sandy/node/<id>/cam/{command,event,status}. The camera
shares the robot's node_id.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from pymongo.errors import PyMongoError

logger = logging.getLogger(__name__)

# Photos land in Mongo so any worker can serve the request, however slow the board is.
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
             # TTL index: the sweep below only runs when another photo arrives.
             "expire_at": datetime.now(timezone.utc) + timedelta(seconds=_INBOX_TTL_S)},
            upsert=True)
        col.delete_many({"at": {"$lt": time.time() - _INBOX_TTL_S}})
    except PyMongoError as e:
        logger.warning("[camera] could not store photo %s: %s", req_id, e)


def _inbox_put_error(node_id: str, req_id: str, reason: str) -> None:
    """Record that a photo is not coming, so the caller stops waiting for it."""
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
    """Publish on the camera's service channel.

    Not send_to_topic (cam/command is not a device); ownership is checked on the node instead.
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
    """Ask for a photo and return a ticket at once; the caller polls fetch_snapshot."""
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
    """Called by the upload endpoint with the finished JPEG."""
    _inbox_put((node_id or "").strip(), (req_id or "").strip(), jpeg)


def fetch_snapshot(node_id: str, req_id: str) -> Optional[bytes]:
    node_id, req_id = (node_id or "").strip(), (req_id or "").strip()
    if not node_id or not req_id:
        return None
    return _inbox_get(node_id, req_id)


_ERROR_TEXT = {
    "camera_init_failed_at_boot": "الكاميرا ما اشتغلت من الإقلاع — افحص كبل الكاميرا والكهربا.",
    "capture_failed": "الكاميرا ما قدرت تصوّر. جرّب كمان مرّة.",
    "upload_failed": "الصورة انأخذت بس ما قدرت توصل للخادم. تأكد من شبكة الكاميرا.",
    "camera_busy": "الكاميرا مشغولة بلقطة تانية.",
}


def on_event(node_id: str, payload: str) -> None:
    """A ``cam/event``: an error for a request becomes that request's answer."""
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
    """``{"error", "message"}`` if the camera said the photo is not coming, else None."""
    node_id, req_id = (node_id or "").strip(), (req_id or "").strip()
    if not node_id or not req_id:
        return None
    code = _inbox_get_error(node_id, req_id)
    if not code:
        return None
    return {"error": code,
            "message": _ERROR_TEXT.get(code, "الكاميرا ما قدرت تجيب الصورة.")}
