"""Each board's own voice HMAC key, so one opened robot doesn't unlock the fleet.

After pairing, a shared-key hello is answered with a fresh per-board key
(``issued``); the board's first hello signed with it (``"kv": 2``) marks it
``confirmed`` and the shared key is refused for that board from then on. Keys
are only handed out within ENROL_WINDOW_MIN of pairing. Stored encrypted when
SANDY_LTM_KEY is set; keyed by device id (read before any tenant exists).
"""

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from app.db import get_db

logger = logging.getLogger(__name__)

_COLL = "sandy_device_keys"
KEY_VERSION = 2          # the `kv` a hello signed with the board's own key carries
ENROL_WINDOW_MIN = 15    # how long after pairing a board may collect its key


class KeyUnreadable(RuntimeError):
    """A key is on record but this server cannot read it (SANDY_LTM_KEY wrong or
    changed). Not the board's fault: callers answer with a temporary error, never
    with "unknown key", which makes the board throw its key away."""


def cam_key_id(node_id: str) -> str:
    """Camera's key id: shares the node id, but must not share the robot's key."""
    return f"{(node_id or '').strip()}:cam"


def _coll():
    db = get_db()
    return None if db is None else db[_COLL]


def get_key(device_id: str) -> Optional[Dict[str, Any]]:
    """``{"key": bytes, "state": "issued"|"confirmed"}`` or None when there is none.

    Raises KeyUnreadable when a record exists that cannot be decrypted."""
    coll = _coll()
    device_id = (device_id or "").strip()
    if coll is None or not device_id:
        return None
    doc = coll.find_one({"_id": device_id})
    if not doc or not doc.get("key"):
        return None
    from app.utils.ltm_crypto import decrypt_field

    hex_key = decrypt_field(str(doc["key"]))
    try:
        key = bytes.fromhex(hex_key)
    except ValueError:
        logger.error("[device_keys] stored key for %s is unreadable", device_id)
        raise KeyUnreadable(device_id) from None
    return {"key": key, "hex": hex_key, "state": doc.get("state", "issued")}


def issue_key(device_id: str) -> Optional[str]:
    """The board's pending key as hex (re-sent, not replaced, if already issued)."""
    coll = _coll()
    device_id = (device_id or "").strip()
    if coll is None or not device_id:
        return None
    current = get_key(device_id)
    if current and current["state"] != "issued":
        return None
    if coll.find_one({"_id": device_id,
                      "enrol_until": {"$gt": datetime.now(timezone.utc)}}) is None:
        return None
    if current:
        return current["hex"]
    from app.utils.ltm_crypto import encrypt_field

    hex_key = secrets.token_hex(32)
    # Only fills a keyless record, so a concurrent issue keeps its key.
    coll.update_one(
        {"_id": device_id, "key": {"$exists": False}},
        {"$set": {"key": encrypt_field(hex_key), "state": "issued",
                  "issued_at": datetime.now(timezone.utc)}},
    )
    stored = get_key(device_id)
    return stored["hex"] if stored and stored["state"] == "issued" else None


def open_enrolment(device_id: str, minutes: int = ENROL_WINDOW_MIN) -> None:
    """Owner just paired: open the key window (never for an already-confirmed key)."""
    coll = _coll()
    device_id = (device_id or "").strip()
    if coll is None or not device_id:
        return
    until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    coll.update_one({"_id": device_id, "state": {"$ne": "confirmed"}},
                    {"$set": {"enrol_until": until}}, upsert=False)
    if coll.find_one({"_id": device_id}) is None:
        coll.insert_one({"_id": device_id, "enrol_until": until})


def confirm_key(device_id: str) -> None:
    """The board signed with its own key: the shared key is refused from now."""
    coll = _coll()
    if coll is None:
        return
    coll.update_one(
        {"_id": (device_id or "").strip(), "state": "issued"},
        {"$set": {"state": "confirmed", "confirmed_at": datetime.now(timezone.utc)}},
    )
    logger.info("[device_keys] %s now authenticates with its own key", device_id)


def revoke_key(device_id: str) -> None:
    """Forget the board's key (un-pairing). It re-enrols after its next pairing."""
    coll = _coll()
    if coll is None:
        return
    coll.delete_one({"_id": (device_id or "").strip()})
