"""Per-board broker credentials, so one opened board can't read the whole fleet.

Delivered over the voice link (HMAC-authenticated, independent of the shared
broker login being retired). ``SANDY_BROKER_CREDS`` is a JSON object keyed by
device id: {"sandy0001": {"user": "node-0001", "pass": "…"}}. A device with no
row gets nothing and keeps its current credential, and only a paired board gets its row:
a board nobody paired reaches the broker with the login its factory partition carries,
which is how a new robot shows its pairing code.

Issuing and revoking is the owner's, by hand on the broker (the free plan has no API for
it). A release lists the board's login for revoking (`note_released`); `to_revoke` is the
list, on the owner's diagnose, until its row leaves the table.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import PyMongoError

from app.db import get_db

logger = logging.getLogger(__name__)

_ENV_VAR = "SANDY_BROKER_CREDS"
# Released boards whose own broker login is still live on the broker, keyed by device.
_REVOKE = "broker_logins_to_revoke"

_table: Optional[Dict[str, Dict[str, str]]] = None
_warned = False


def _load() -> Dict[str, Dict[str, str]]:
    global _table, _warned
    if _table is not None:
        return _table

    from app import config

    raw = (getattr(config, "SANDY_BROKER_CREDS", "") or "").strip()
    if not raw:
        _table = {}
        return _table

    try:
        parsed: Any = json.loads(raw)
    except ValueError as exc:
        # Logged once: a typo here silently disables the feature.
        if not _warned:
            logger.error("[broker_creds] %s is not valid JSON: %s", _ENV_VAR, exc)
            _warned = True
        _table = {}
        return _table

    if not isinstance(parsed, dict):
        if not _warned:
            logger.error("[broker_creds] %s must be a JSON object keyed by device id",
                         _ENV_VAR)
            _warned = True
        _table = {}
        return _table

    table: Dict[str, Dict[str, str]] = {}
    for device_id, row in parsed.items():
        if not isinstance(row, dict):
            continue
        user = str(row.get("user") or "").strip()
        password = str(row.get("pass") or "").strip()
        if not user or not password:
            # Half a credential would break the board with no fallback.
            logger.warning("[broker_creds] %s has no usable user/pass — skipped",
                           device_id)
            continue
        table[str(device_id).strip()] = {"user": user, "pass": password}

    _table = table
    logger.info("[broker_creds] %d device credential(s) configured", len(table))
    return _table


def creds_for_device(device_id: str) -> Optional[Dict[str, str]]:
    """This board's own broker login, or None to leave it unchanged."""
    device_id = (device_id or "").strip()
    if not device_id:
        return None
    return _load().get(device_id)


def reset_cache() -> None:
    """For tests."""
    global _table, _warned
    _table = None
    _warned = False


def note_released(device_id: str) -> None:
    """A board was released: its own login stays live on the broker (and in the board) until
    the owner revokes it there, so it goes on the list. A board with no row has none."""
    creds = creds_for_device(device_id)
    db = get_db()
    if not creds or db is None:
        return
    try:
        db[_REVOKE].update_one({"_id": device_id}, {"$set": {
            "user": creds["user"], "since": datetime.now(timezone.utc)}}, upsert=True)
        logger.warning("[broker_creds] %s was released: revoke broker login %s on the "
                       "broker and remove its row from %s", device_id, creds["user"], _ENV_VAR)
    except PyMongoError as exc:
        logger.error("[broker_creds] %s released but its login %s was not listed for "
                     "revoking: %s", device_id, creds["user"], exc)


def to_revoke() -> List[Dict[str, Any]]:
    """The logins still to revoke: a row whose login left the table (revoked and removed,
    or replaced by a new one for the next owner) is done and goes."""
    db = get_db()
    if db is None:
        return []
    out = []
    try:
        for row in db[_REVOKE].find({}).sort("since", 1).limit(500):
            current = creds_for_device(row["_id"])
            if not current or current["user"] != row.get("user"):
                db[_REVOKE].delete_one({"_id": row["_id"]})
                continue
            since = row.get("since")
            out.append({"device": row["_id"], "user": row.get("user"),
                        "since": since.isoformat() if isinstance(since, datetime) else ""})
    except PyMongoError as exc:
        logger.warning("[broker_creds] revoke list not read: %s", exc)
    return out
