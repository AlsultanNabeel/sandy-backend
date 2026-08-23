"""The broker credential a single board is allowed to use.

Every board sold today carries the same broker username and password, compiled
in. That means any customer can subscribe to any other customer's topics — the
sound of their house, the pictures from their camera, the commands they give.
One board opened with a screwdriver exposes the whole fleet, and there is no way
to withdraw a single key without reflashing every unit in the field.

The board already reads its credential from NVS and falls back to the compiled
one. This module is the other half: the place a board's own credential comes
from. The voice link hands it over at the end of the handshake, so a unit picks
up its key on its next boot, over the air, with nobody touching it.

**Why the voice link and not the broker itself.** Delivering a broker credential
over the broker would mean the shared credential has to keep working for ever —
the very thing being retired. The voice socket authenticates with a signature
and a timestamp against a key that is not the broker's, so it stays trustworthy
after the shared broker login is revoked. That is the whole point.

**Why a config table and not the broker's API.** Issuing credentials
programmatically needs the broker's management API, which is a paid plan. The
free plan allows several logins, each restricted to one topic filter — enough to
close the hole today for the boards that exist. So the table lives in one config
var, and `creds_for_device` is the seam: when the fleet outgrows hand-issued
logins, this function calls the API and nothing else changes.

Format of ``SANDY_BROKER_CREDS`` (read through ``app.config``) — a JSON object
keyed by device id:

    {"sandy0001": {"user": "node-0001", "pass": "…"},
     "sandy0002": {"user": "node-0002", "pass": "…"}}

A device with no row gets nothing, and keeps whatever it already has. That is
deliberate: an empty or malformed config must leave working robots working, not
push them a blank credential and take the fleet off the air.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_ENV_VAR = "SANDY_BROKER_CREDS"

# Parsed once. Re-reading and re-parsing per handshake would be work per boot of
# every robot for a value that cannot change without a restart anyway.
_table: Optional[Dict[str, Dict[str, str]]] = None
_warned = False


def _load() -> Dict[str, Dict[str, str]]:
    global _table, _warned
    if _table is not None:
        return _table

    # القراءة بتمرّ من `app.config` — هي المكان الوحيد اللي بيلمس البيئة
    # بالمشروع، وفي حارس بالاختبارات بيمنع القراءات المباشرة تكتر.
    from app import config

    raw = (getattr(config, "SANDY_BROKER_CREDS", "") or "").strip()
    if not raw:
        _table = {}
        return _table

    try:
        parsed: Any = json.loads(raw)
    except ValueError as exc:   # JSONDecodeError — the only thing loads raises here
        # Loud, once. A typo here silently means "no board ever gets its own
        # key", which looks exactly like the feature not existing.
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
            # Half a credential is worse than none — the board would store it
            # and then fail to connect with no fallback left.
            logger.warning("[broker_creds] %s has no usable user/pass — skipped",
                           device_id)
            continue
        table[str(device_id).strip()] = {"user": user, "pass": password}

    _table = table
    logger.info("[broker_creds] %d device credential(s) configured", len(table))
    return _table


def creds_for_device(device_id: str) -> Optional[Dict[str, str]]:
    """This board's own broker login, or None to leave it as it is.

    Returning None is the normal answer for a board that has not been issued a
    credential yet, and it must stay harmless: the board keeps the credential it
    is running on.
    """
    device_id = (device_id or "").strip()
    if not device_id:
        return None
    return _load().get(device_id)


def reset_cache() -> None:
    """Forget the parsed table. For tests, and for a config reload in a shell."""
    global _table, _warned
    _table = None
    _warned = False
