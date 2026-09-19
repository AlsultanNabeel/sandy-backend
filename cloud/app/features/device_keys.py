"""Each board's own voice key — so one opened robot does not unlock the fleet.

Until now every brain and camera signed its voice hello with the same
``SANDY_WS_HMAC_KEY``, compiled in. The handshake then acts as whatever
``device_id`` the board names: it takes the owner's identity and hands out that
board's private broker login. Reading the key out of one robot's flash was
enough to speak to Sandy as any customer and take over their robot's topics.

**How a board gets its own key.** Once a board is paired, its next hello signed
with the shared key is answered with ``auth_ok`` plus a fresh random key for
that board (``issued``). The board stores it and signs every later hello with it
(``"kv": 2``); the first such hello marks the key ``confirmed``. From then on the
shared key is refused for that board — the key is the board's, and only the
board has it.

**The enrolment window.** A key is handed out only in the
``ENROL_WINDOW_MIN`` minutes after the owner pairs the board in the app (pairing
the same code again reopens it — that is how a board that missed its window, or
one un-paired and re-paired, gets back in). Outside that window a shared-key
hello still works as before, it just never carries a key.

Without the window, anyone holding the shared key could ask for any board's key
at any time before that board enrolled — and a board whose owner never updated
it would stay claimable forever. With it, they would have to act in the same few
minutes the owner is pairing, as that board's id. After confirmation the shared
key no longer impersonates the board at all. Closing the window completely needs
the key written at flash time instead (see ARCHITECTURE_MAP §12); this table is
also where that would store it.

Keys are stored encrypted when ``SANDY_LTM_KEY`` is set (``ltm_crypto``).
Keyed by device id, across tenants: this is device infrastructure, read on the
handshake before any tenant exists.
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


def cam_key_id(node_id: str) -> str:
    """The camera's own record. It shares the robot's node id (same pairing
    code), so it needs a separate key id — one opened camera must not yield the
    robot's key, nor the other way round."""
    return f"{(node_id or '').strip()}:cam"


def _coll():
    db = get_db()
    return None if db is None else db[_COLL]


def get_key(device_id: str) -> Optional[Dict[str, Any]]:
    """``{"key": bytes, "state": "issued"|"confirmed"}`` or None."""
    coll = _coll()
    device_id = (device_id or "").strip()
    if coll is None or not device_id:
        return None
    doc = coll.find_one({"_id": device_id})
    if not doc or not doc.get("key"):
        return None
    from app.agent.ltm_crypto import decrypt_field

    hex_key = decrypt_field(str(doc["key"]))
    try:
        key = bytes.fromhex(hex_key)
    except ValueError:
        logger.error("[device_keys] stored key for %s is unreadable", device_id)
        return None
    return {"key": key, "hex": hex_key, "state": doc.get("state", "issued")}


def issue_key(device_id: str) -> Optional[str]:
    """The board's pending key (a new one if none is pending), as hex.

    A key that is already ``issued`` is handed out again rather than replaced:
    a board that dropped the reply before storing it must get the same key on
    its next try, or two tries could leave the board and the server disagreeing.
    """
    coll = _coll()
    device_id = (device_id or "").strip()
    if coll is None or not device_id:
        return None
    current = get_key(device_id)
    if current and current["state"] != "issued":
        return None
    if coll.find_one({"_id": device_id,
                      "enrol_until": {"$gt": datetime.now(timezone.utc)}}) is None:
        # No pairing just happened. Not an error — the board keeps working on
        # the shared key and collects its own the next time it is paired.
        return None
    if current:
        return current["hex"]
    from app.agent.ltm_crypto import encrypt_field

    hex_key = secrets.token_hex(32)
    # Only fills a record that has no key yet: a concurrent issue that won
    # keeps its key, and the re-read below returns that one.
    coll.update_one(
        {"_id": device_id, "key": {"$exists": False}},
        {"$set": {"key": encrypt_field(hex_key), "state": "issued",
                  "issued_at": datetime.now(timezone.utc)}},
    )
    # Re-read: a concurrent issue may have won the upsert.
    stored = get_key(device_id)
    return stored["hex"] if stored and stored["state"] == "issued" else None


def open_enrolment(device_id: str, minutes: int = ENROL_WINDOW_MIN) -> None:
    """The owner just paired this board: it may collect its key for a while.

    A board that already has a confirmed key is left alone — pairing again must
    not hand a second copy of a key the board is already using.
    """
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
