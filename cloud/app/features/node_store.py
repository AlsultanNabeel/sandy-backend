"""Node registry — paired Sandy nodes (the pre-flashed ESP boxes we sell).

A node is one physical ESP running the generic firmware. The customer powers it,
then **pairs** it in the app by entering the code printed on the box. Pairing binds
that code to the tenant; from then on the node's devices live under that tenant.

Collection: sandy_nodes (tenant-scoped via scoped())
  {
    _id, user_id (injected by scoped),
    node_id,           # our stable id for the node (generated at pairing)
    label,             # "صندوق الصالة"
    code_hash,         # sha256 of the factory pairing code (never store raw)
    capabilities,      # ["relay","pwm","servo","buzzer","ir","audio"] (node-reported)
    outputs,           # [{id:"relay1", kind:"relay"}, ...] (node-reported)
    firmware_version,
    online, last_seen, # heartbeat, for the diagnosis layer
    paired_at,
  }

Pure data: this module does not talk MQTT. The firmware reports heartbeat/caps
through the ingest path, which calls set_node_status().
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.utils.tenant_db import scoped

logger = logging.getLogger(__name__)

_COLL = "sandy_nodes"
_mongo_db = None

# Capabilities a node may advertise. Validated so a bad heartbeat can't inject junk.
KNOWN_CAPABILITIES = frozenset({"relay", "pwm", "servo", "buzzer", "ir", "audio"})


def init_node_store(mongo_db) -> None:
    global _mongo_db
    _mongo_db = mongo_db
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index(
            [("user_id", 1), ("node_id", 1)], unique=True, background=True
        )
        # Heartbeat ingest looks nodes up by code hash across tenants.
        mongo_db[_COLL].create_index([("code_hash", 1)], background=True)
        logger.info("[NodeStore] ready")
    except Exception as e:  # noqa: BLE001
        logger.warning("[NodeStore] index skipped: %s", e)


def _coll():
    """Tenant-scoped nodes collection, or None when no db / no active tenant."""
    return scoped(_mongo_db, _COLL)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Any) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else ""


def _hash_code(code: str) -> str:
    return hashlib.sha256((code or "").strip().lower().encode("utf-8")).hexdigest()


def code_to_node_id(code: str) -> str:
    """Deterministic node_id from the printed pairing code: lowercase alphanumerics.

    The node is flashed with its code and derives the SAME id, so it knows its MQTT
    topic (sandy/node/<node_id>/...) before it is ever paired — no provisioning
    handshake needed. The firmware must apply this identical transform.
    """
    return re.sub(r"[^a-z0-9]", "", (code or "").strip().lower())


def _public(d: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "node_id": d.get("node_id", ""),
        "label": d.get("label", ""),
        "capabilities": d.get("capabilities", []),
        "outputs": d.get("outputs", []),
        "firmware_version": d.get("firmware_version", ""),
        "online": bool(d.get("online", False)),
        "last_seen": _iso(d.get("last_seen")),
        "paired_at": _iso(d.get("paired_at")),
    }


def _clean_caps(caps: Any) -> List[str]:
    if not isinstance(caps, list):
        return []
    return [c for c in (str(x).strip().lower() for x in caps) if c in KNOWN_CAPABILITIES]


# ── Pairing ─────────────────────────────────────────────────────────────────

def pair_node(code: str, label: str = "") -> Dict[str, Any]:
    """Bind a factory pairing code to the current tenant.

    The raw code is hashed (never stored). Re-pairing the same code under the same
    tenant is a no-op that returns the existing node, so the flow is idempotent.
    """
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    code = (code or "").strip()
    if len(code) < 4:
        return {"ok": False, "error": "bad_code"}
    code_hash = _hash_code(code)

    existing = coll.find_one({"code_hash": code_hash})
    if existing is not None:
        return {"ok": True, "node_id": existing["node_id"], "already": True}

    # node_id = the code itself (slugified) so the firmware's topic is deterministic.
    node_id = code_to_node_id(code)
    if not node_id:
        return {"ok": False, "error": "bad_code"}
    coll.insert_one({
        "node_id": node_id,
        "label": (label or "Sandy node").strip(),
        "code_hash": code_hash,
        "capabilities": [],
        "outputs": [],
        "firmware_version": "",
        "online": False,
        "paired_at": _now(),
    })
    return {"ok": True, "node_id": node_id, "already": False}


def list_nodes() -> List[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return []
    return [_public(d) for d in coll.find({}).sort("paired_at", 1)]


def get_node(node_id: str) -> Optional[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return None
    return coll.find_one({"node_id": (node_id or "").strip()}) or None


def rename_node(node_id: str, label: str) -> Dict[str, Any]:
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    label = (label or "").strip()
    if not label:
        return {"ok": False, "error": "bad_label"}
    r = coll.update_one({"node_id": (node_id or "").strip()},
                        {"$set": {"label": label}})
    if r.matched_count == 0:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "node_id": node_id}


def unpair_node(node_id: str) -> Dict[str, Any]:
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    r = coll.delete_one({"node_id": (node_id or "").strip()})
    if r.deleted_count == 0:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "node_id": node_id}


# ── Heartbeat ingest (called by the firmware-facing path, not tenant-scoped) ──

def set_node_status(code: str, online: bool = True,
                    capabilities: Optional[List[str]] = None,
                    outputs: Optional[List[Dict[str, Any]]] = None,
                    firmware_version: str = "") -> Dict[str, Any]:
    """Update a node's heartbeat by its pairing code (firmware speaks code, not
    node_id). Looked up across tenants by code hash. Best-effort; never raises."""
    if _mongo_db is None:
        return {"ok": False, "error": "no_store"}
    try:
        update: Dict[str, Any] = {"online": bool(online), "last_seen": _now()}
        if capabilities is not None:
            update["capabilities"] = _clean_caps(capabilities)
        if isinstance(outputs, list):
            update["outputs"] = outputs
        if firmware_version:
            update["firmware_version"] = str(firmware_version)[:32]
        r = _mongo_db[_COLL].update_one(
            {"code_hash": _hash_code(code)}, {"$set": update}
        )
        if r.matched_count == 0:
            return {"ok": False, "error": "unknown_node"}
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        logger.debug("[NodeStore] set_node_status failed: %s", e)
        return {"ok": False, "error": "exception"}
