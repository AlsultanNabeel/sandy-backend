"""Node registry (sandy_nodes): paired Sandy boards, bound to a tenant by the code on the box.

Stores node_id, label, code_hash (never the raw code), capabilities, outputs,
firmware_version, online/last_seen, telemetry, paired_at. Pure data: heartbeats
arrive via integrations/mqtt_ingest.py → ingest_status().
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.utils.tenant_db import scoped
from app.db import configure, get_db

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

_COLL = "sandy_nodes"

# سقف أمان، مش حد منتج.
MAX_NODES = 100

KNOWN_CAPABILITIES = frozenset({"relay", "pwm", "servo", "buzzer", "ir", "audio"})


def init_node_store(mongo_db) -> None:
    configure(mongo_db)
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index(
            [("user_id", 1), ("node_id", 1)], unique=True, background=True
        )
        # Heartbeat ingest looks nodes up by code hash across tenants.
        mongo_db[_COLL].create_index([("code_hash", 1)], background=True)
        # One owner per board, enforced by the database (the read-then-insert check races).
        mongo_db[_COLL].create_index(
            [("node_id", 1)], unique=True, background=True, name="node_id_owner_unique"
        )
        logger.info("[NodeStore] ready")
    except Exception as e:  # noqa: BLE001
        logger.warning("[NodeStore] index skipped: %s", e)


def _coll():
    return scoped(get_db(), _COLL)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Any) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else ""


def _hash_code(code: str) -> str:
    return hashlib.sha256((code or "").strip().lower().encode("utf-8")).hexdigest()


def code_to_node_id(code: str) -> str:
    """node_id from the printed pairing code (lowercase alphanumerics); the firmware applies the same transform."""
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
        "telemetry": d.get("telemetry", {}),
    }


# Allowlist: heartbeats come from unauthenticated devices over a shared broker.
_TELEMETRY_KEYS = {
    "mic_l": int, "mic_r": int,
    "mic_l_gain": int, "mic_r_gain": int,
    "mic_l_muted": bool, "mic_r_muted": bool,
    "volume": int, "noise": int,
    "uptime": int, "heap": int, "mood": int,
    # Boards share a node id, so each board's fields get their own prefix.
    "ip": str, "board": str,
    "cam_boot": int,
    "cam_ip": str, "cam_board": str, "cam_ssid": str,
    # cam_stream_key: random per boot; the app needs it to open the local stream.
    "cam_fw": str, "cam_online": bool, "cam_stream_key": str,
    "room_ip": str, "room_board": str, "room_light": str,
    "room_fw": str, "room_online": bool, "room_uptime_s": int, "room_heap": int,
    "ssid": str,
    # dBm; below about -75 the link can't carry live voice.
    "rssi": int, "room_rssi": int,
}


def _clean_telemetry(data: Any) -> Dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    out: Dict[str, Any] = {}
    for key, kind in _TELEMETRY_KEYS.items():
        if key not in data:
            continue
        try:
            if kind is bool:
                out[key] = bool(data[key])
            elif kind is str:
                # Capped: untrusted input.
                out[key] = str(data[key])[:32]
            else:
                out[key] = int(data[key])
        except (TypeError, ValueError):
            continue
    return out


def _clean_caps(caps: Any) -> List[str]:
    if not isinstance(caps, list):
        return []
    return [c for c in (str(x).strip().lower() for x in caps) if c in KNOWN_CAPABILITIES]


def _clean_outputs(outputs: Any) -> List[Dict[str, Any]]:
    """Keep only well-formed {id, kind} outputs with a known kind (untrusted heartbeat input)."""
    if not isinstance(outputs, list):
        return []
    clean: List[Dict[str, Any]] = []
    for o in outputs[:32]:
        if not isinstance(o, dict):
            continue
        oid = str(o.get("id", "")).strip()[:32]
        kind = str(o.get("kind", "")).strip().lower()
        if oid and kind in KNOWN_CAPABILITIES:
            clean.append({"id": oid, "kind": kind})
    return clean


# ── Pairing ─────────────────────────────────────────────────────────────────

def _provision(node_id: str, outputs: Any, label: str = "") -> None:
    """Create devices for declared outputs in the current tenant; never fails a pairing."""
    if not isinstance(outputs, list) or not outputs:
        return
    try:
        from app.features.node_provision import provision_from_outputs
        provision_from_outputs(node_id, outputs, label)
    except Exception as e:  # noqa: BLE001
        logger.warning("[NodeStore] provisioning %s failed: %s", node_id, e)


def _is_legacy_owner(user_id: Any) -> bool:
    """هل هالحساب هو حساب «المالك» القديم (ما عاد فيه دخول)؟ سؤال أمني: أي توسيع بيسمح بأخذ روبوت حدا تاني."""
    if not user_id:
        return False
    try:
        from app.features import users_store
        owner = users_store.get_user(str(user_id)) or {}
        return str(owner.get("provider") or "") == "owner"
    except Exception:  # noqa: BLE001 — الافتراض الآمن الرفض
        return False


def pair_precheck(code: str) -> Dict[str, Any]:
    """Pairing state before writing: ``ours``, ``claimed`` by another account, or ``free``."""
    code = (code or "").strip()
    node_id = code_to_node_id(code)
    if len(code) < 4 or not node_id:
        return {"state": "bad_code"}
    coll = _coll()
    if coll is None:
        return {"state": "no_store"}
    if coll.find_one({"code_hash": _hash_code(code)}) is not None:
        return {"state": "ours", "node_id": node_id}
    if get_db() is not None:
        claimed = get_db()[_COLL].find_one({"node_id": node_id})
        if claimed is not None and not _is_legacy_owner(claimed.get("user_id")):
            return {"state": "claimed", "node_id": node_id}
    return {"state": "free", "node_id": node_id}


def pair_node(code: str, label: str = "") -> Dict[str, Any]:
    """Bind a factory pairing code to the current tenant (idempotent for the same tenant)."""
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    code = (code or "").strip()
    if len(code) < 4:
        return {"ok": False, "error": "bad_code"}
    code_hash = _hash_code(code)

    existing = coll.find_one({"code_hash": code_hash})
    if existing is not None:
        # Already ours; still provision (it may have paired before any heartbeat).
        _provision(existing["node_id"], existing.get("outputs"),
                   existing.get("label", ""))
        _open_key_enrolment(existing["node_id"])
        return {"ok": True, "node_id": existing["node_id"], "already": True}

    node_id = code_to_node_id(code)
    if not node_id:
        return {"ok": False, "error": "bad_code"}

    # مطالَبة مرّة وحدة عبر كل الحسابات: أول حساب بيربط بيملك.
    if get_db() is not None:
        # لو فشلت القراءة ما بنكمل: «ما قدرت أتأكد» لازم يوقف المطالبة.
        claimed = get_db()[_COLL].find_one({"node_id": node_id})
        if claimed is not None and not _is_legacy_owner(claimed.get("user_id")):
            logger.warning("[NodeStore] %s already claimed — refusing", node_id)
            return {"ok": False, "error": "already_claimed"}
        if claimed is not None:
            # استثناء ضيّق: الحساب «المالك» القديم ما فيه دخول، فبدونه صاحب الروبوت بينقفل برّاه.
            logger.info("[NodeStore] %s was held by the pre-accounts owner — "
                        "handing it to its new account", node_id)
            get_db()[_COLL].delete_one({"_id": claimed["_id"]})

    try:
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
    except DuplicateKeyError:
        logger.warning("[NodeStore] %s claimed concurrently — refusing", node_id)
        return {"ok": False, "error": "already_claimed"}
    _open_key_enrolment(node_id)
    return {"ok": True, "node_id": node_id, "already": False}


def _open_key_enrolment(node_id: str) -> None:
    """Pairing is when the owner vouches for the board: open its voice-key enrolment."""
    try:
        from app.features.device_keys import cam_key_id, open_enrolment
        open_enrolment(node_id)
        open_enrolment(cam_key_id(node_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[NodeStore] key enrolment not opened for %s: %s", node_id, exc)


def list_nodes() -> List[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return []
    return [_public(d) for d in coll.find({}).sort("paired_at", 1).limit(MAX_NODES)]


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


def _wipe_board(node_id: str) -> bool:
    """Tell the board to forget its network credentials. Best effort."""
    try:
        from app.integrations.room_device import get_room_device_client

        return bool(get_room_device_client().publish_service(
            f"sandy/node/{node_id}/factory_reset", "erase"))
    except Exception as exc:  # noqa: BLE001 — an offline board must not block the release
        logger.warning("[NodeStore] factory reset not delivered to %s: %s",
                       node_id, exc)
        return False


def unpair_node(node_id: str) -> Dict[str, Any]:
    """Release a node and every device that actuates through it.

    The board obeys any topic built from its code, so its devices must be deleted,
    not flagged. Returns the device count and whether the board was wiped.
    """
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    node_id = (node_id or "").strip()
    if not coll.find_one({"node_id": node_id}, {"_id": 1}):
        return {"ok": False, "error": "not_found"}

    # Wipe the board first, while the caller still owns it (account deletion also
    # comes through here). An offline board doesn't block the release.
    board_wiped = _wipe_board(node_id)

    from app.features.device_store import delete_devices_for_node

    # Devices before the node row, so a racing heartbeat can't re-provision them.

    devices_removed = delete_devices_for_node(node_id)
    # A sold robot must enrol a fresh voice key.
    try:
        from app.features.device_keys import cam_key_id, revoke_key
        revoke_key(node_id)
        revoke_key(cam_key_id(node_id))
    except Exception as exc:  # noqa: BLE001
        logger.warning("[NodeStore] could not revoke the voice key of %s: %s",
                       node_id, exc)
    r = coll.delete_one({"node_id": node_id})
    if r.deleted_count == 0:
        return {"ok": False, "error": "not_found",
                "devices_removed": devices_removed, "board_wiped": board_wiped}
    return {"ok": True, "node_id": node_id,
            "devices_removed": devices_removed, "board_wiped": board_wiped}


# ── Heartbeat ingest (firmware-facing, runs outside a tenant) ────────────────
# Several boards share one node id; each heartbeat merges only its own board's
# outputs and telemetry, or they erase each other in a loop.

def _output_namespace(output_id: Any) -> str:
    """The board prefix of an output id: ``cam/``, ``room/``, or "" for the brain."""
    oid = str(output_id or "")
    head, sep, _ = oid.partition("/")
    return head + sep if sep else ""


def _merge_outputs(node_id: str, incoming: List[Dict[str, Any]],
                   current: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """Replace only the namespaces this heartbeat declares; declaring nothing keeps everything.

    ``current`` is the node document when the caller already read it.
    """
    fresh = _clean_outputs(incoming)
    claimed = {_output_namespace(o.get("id")) for o in fresh}

    if current is None:
        current = get_node_any_tenant(node_id) or {}
    existing = current.get("outputs") or []
    kept = [
        o for o in existing
        if isinstance(o, dict) and _output_namespace(o.get("id")) not in claimed
    ]
    return kept + fresh


def _merge_telemetry(current: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    """Update only the keys this heartbeat carries."""
    fresh = _clean_telemetry(incoming)
    existing = current.get("telemetry") or {}
    if not isinstance(existing, dict):
        existing = {}
    return {**existing, **fresh}


def get_node_any_tenant(node_id: str) -> Optional[Dict[str, Any]]:
    """One node by id across tenants — ingest path only, never a request handler."""
    if get_db() is None:
        return None
    try:
        return get_db()[_COLL].find_one({"node_id": (node_id or "").strip()})
    except Exception:  # noqa: BLE001
        return None


def ingest_status(node_id: str, online: Optional[bool] = True,
                  capabilities: Optional[List[str]] = None,
                  outputs: Optional[List[Dict[str, Any]]] = None,
                  firmware_version: str = "",
                  telemetry: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Heartbeat update by node_id, cross-tenant; best-effort, never raises.

    ``online=None`` leaves online/last_seen alone (camera and room node report their own).
    """
    if get_db() is None:
        return {"ok": False, "error": "no_store"}
    try:
        node_id = (node_id or "").strip()
        # Read once; both merges and provisioning use it.
        current = get_node_any_tenant(node_id)
        if current is None:
            # Not paired yet.
            return {"ok": False}
        update: Dict[str, Any] = {}
        if online is not None:
            update["online"] = bool(online)
            update["last_seen"] = _now()
        if capabilities is not None:
            update["capabilities"] = _clean_caps(capabilities)
        if isinstance(outputs, list):
            update["outputs"] = _merge_outputs(node_id, outputs, current)
        if firmware_version:
            update["firmware_version"] = str(firmware_version)[:32]
        if telemetry is not None:
            update["telemetry"] = _merge_telemetry(current, telemetry)
        if not update:
            return {"ok": True}
        r = get_db()[_COLL].update_one({"node_id": node_id}, {"$set": update})
        if r.matched_count == 0:
            return {"ok": False}   # unpaired between the read and the write

        # New outputs become devices, so a firmware upgrade shows up without re-pairing.
        if update.get("outputs") and current.get("user_id"):
            from app.features.node_provision import provision_for_owner
            provision_for_owner(node_id, str(current["user_id"]),
                                update["outputs"], str(current.get("label", "")))
        return {"ok": True}
    except Exception as e:  # noqa: BLE001
        logger.debug("[NodeStore] ingest_status failed: %s", e)
        return {"ok": False, "error": "exception"}


def set_last_ir(node_id: str, code: str) -> Dict[str, Any]:
    """Record the last IR code a node captured in learn mode (cross-tenant)."""
    if get_db() is None:
        return {"ok": False, "error": "no_store"}
    try:
        r = get_db()[_COLL].update_one(
            {"node_id": (node_id or "").strip()},
            {"$set": {"last_ir": str(code).strip(), "last_ir_at": _now()}},
        )
        return {"ok": r.matched_count > 0}
    except Exception as e:  # noqa: BLE001
        logger.debug("[NodeStore] set_last_ir failed: %s", e)
        return {"ok": False, "error": "exception"}


def get_last_ir(node_id: str) -> Dict[str, Any]:
    """The last captured IR code for a node (tenant-scoped)."""
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    d = coll.find_one({"node_id": (node_id or "").strip()})
    if d is None:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "code": d.get("last_ir", ""), "at": _iso(d.get("last_ir_at"))}
