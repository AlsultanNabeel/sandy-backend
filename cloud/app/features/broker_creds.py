"""Per-board broker credentials, so one opened board can't read the whole fleet.

Delivered over the voice link (HMAC-authenticated, independent of the shared
broker login being retired). ``SANDY_BROKER_CREDS`` is a JSON object keyed by
device id: {"sandy0001": {"user": "node-0001", "pass": "…"}}. A device with no
row gets nothing and keeps its current credential.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_ENV_VAR = "SANDY_BROKER_CREDS"

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
