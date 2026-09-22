"""Proof of presence: pairing a robot needs someone standing in front of it.

The code printed on the box was the whole of pairing. It is four characters,
it is on a sticker, and a photo of the box — a resale listing, a review, an
unboxing video — was enough to claim somebody's robot before they did, and
from then on to listen through it.

Now the printed code only *starts* pairing. The server makes a six-digit code,
sends it to that robot, and she shows it on her face; the account that types it
back has proven it can see her. The code lives five minutes, is compared in
constant time, and five wrong tries end it. Nothing is stored in clear: the
challenge is kept as a hash, bound to the node and the account that asked.

A robot that is off or not yet online never shows the code — the app says so,
and the owner tries again once she is up. That is the one cost, and it is the
point: pairing a robot you cannot see should not work.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from app.db import get_db

logger = logging.getLogger(__name__)

_COLL = "node_pair_challenges"
TTL_SECONDS = 300
MAX_TRIES = 5
DIGITS = 6


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash(node_id: str, tenant: str, code: str) -> str:
    return hashlib.sha256(f"{node_id}|{tenant}|{code}".encode()).hexdigest()


def _aware(dt: Any) -> datetime:
    # Mongo hands datetimes back naive (UTC); mongomock keeps them as given.
    if isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _publish(node_id: str, code: str) -> bool:
    try:
        from app.integrations.room_device import get_room_device_client

        return bool(get_room_device_client().publish_service(
            f"sandy/node/{node_id}/pair_code", code))
    except Exception as exc:  # noqa: BLE001 — the owner retries; never raise here
        logger.warning("[pair_presence] could not reach %s: %s", node_id, exc)
        return False


def start(node_id: str, tenant: str) -> Dict[str, Any]:
    """Make a code for (node, account), send it to the robot. Replaces any
    earlier one for the same pair, so "send again" is just calling this again."""
    db = get_db()
    if db is None or not node_id or not tenant:
        return {"ok": False, "error": "no_store"}
    code = f"{secrets.randbelow(10 ** DIGITS):0{DIGITS}d}"
    db[_COLL].update_one(
        {"node_id": node_id, "tenant": tenant},
        {"$set": {"hash": _hash(node_id, tenant, code), "tries": 0,
                  "expires_at": _now() + timedelta(seconds=TTL_SECONDS),
                  "created_at": _now()}},
        upsert=True,
    )
    sent = _publish(node_id, code)
    logger.info("[pair_presence] challenge for %s (%s)", node_id,
                "sent" if sent else "not delivered")
    return {"ok": True, "sent": sent, "expires_in": TTL_SECONDS}


def confirm(node_id: str, tenant: str, code: str) -> Dict[str, Any]:
    """True only for the live code this account was sent for this robot."""
    db = get_db()
    if db is None:
        return {"ok": False, "error": "no_store"}
    code = "".join(ch for ch in str(code or "") if ch.isdigit())
    doc = db[_COLL].find_one({"node_id": node_id, "tenant": tenant})
    if doc is None:
        return {"ok": False, "error": "presence_missing"}
    if _aware(doc.get("expires_at")) < _now():
        db[_COLL].delete_one({"_id": doc["_id"]})
        return {"ok": False, "error": "presence_expired"}
    if int(doc.get("tries", 0)) >= MAX_TRIES:
        db[_COLL].delete_one({"_id": doc["_id"]})
        return {"ok": False, "error": "presence_locked"}
    if len(code) != DIGITS or not hmac.compare_digest(
            _hash(node_id, tenant, code), str(doc.get("hash", ""))):
        db[_COLL].update_one({"_id": doc["_id"]}, {"$inc": {"tries": 1}})
        left = MAX_TRIES - int(doc.get("tries", 0)) - 1
        return {"ok": False, "error": "presence_wrong", "tries_left": max(left, 0)}
    db[_COLL].delete_one({"_id": doc["_id"]})
    return {"ok": True}

