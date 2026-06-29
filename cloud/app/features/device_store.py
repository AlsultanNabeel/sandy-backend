"""Device registry — the single source of truth for controllable devices.

Devices are **data, not code**. Each tenant owns a list of devices; the brain,
the scenes, and the app all read from this one registry. Adding a new device is a
row here (plus, for IR, a one-time learn step) — never new code per device.

This is what ends the "turn the light on -> applied the off scene" hallucination:
the control layer may only act on a **registered** device with a **validated**
action; anything unknown is refused (the caller asks), never guessed.

Collection: sandy_devices (tenant-scoped via scoped())
  {
    _id, user_id (injected by scoped),
    name,          # stable slug, unique per tenant ("living_light")
    label,         # human label ("ضوء الصالة")
    room,          # optional grouping ("salon")
    control_type,  # switch | dimmer | enum | media | cover | ir  (see CONTROL_TYPES)
    transport,     # how to reach it: {"kind": "mqtt", "topic": "room/cmd/light"}
    meta,          # type-specific: {values:[...]} for enum, {min,max} for dimmer,
                   #                 {buttons:{name: code}} for ir
    state,         # last known payload we sent ("" until first command)
    online,        # last heartbeat seen (bool) — for diagnosis
    last_seen,     # ISO of last heartbeat
    builtin,       # seeded default (resettable, not deletable)
    updated_at,
  }

Pure data + validation: this module does NOT actuate hardware. `command_payload`
returns the validated payload string; the caller (device_control tool / API)
routes it to the transport.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.utils.tenant_db import scoped

logger = logging.getLogger(__name__)

_COLL = "sandy_devices"
_mongo_db = None

# ── Control types ───────────────────────────────────────────────────────────
# Each control_type defines the actions it accepts. Validation is centralized in
# command_payload() so no caller can invent an action/value.
#
#   switch  — on | off
#   dimmer  — on | off | <int in [min,max]>           (meta.min/max, default 0..100)
#   enum    — set one of meta.values (or pass the value directly)
#   media   — on | off | pause
#   cover   — open | close | stop
#   ir      — send a learned button in meta.buttons (learn flow adds buttons)
CONTROL_TYPES = frozenset({"switch", "dimmer", "enum", "media", "cover", "ir"})

_MEDIA_ACTIONS = {"on", "off", "pause"}
_COVER_ACTIONS = {"open", "close", "stop"}
_SWITCH_ACTIONS = {"on", "off"}

_NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")

# No devices are seeded from code. The registry starts empty per tenant; the owner
# adds every device from the app. This keeps hardware fully decoupled from code.


def init_device_store(mongo_db) -> None:
    global _mongo_db
    _mongo_db = mongo_db
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index(
            [("user_id", 1), ("name", 1)], unique=True, background=True
        )
        logger.info("[DeviceStore] ready")
    except Exception as e:  # noqa: BLE001
        logger.warning("[DeviceStore] index skipped: %s", e)


def _coll():
    """Tenant-scoped devices collection, or None when no db / no active tenant."""
    return scoped(_mongo_db, _COLL)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Any) -> str:
    return dt.isoformat() if isinstance(dt, datetime) else ""


# ── Validation ──────────────────────────────────────────────────────────────

def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def command_payload(device: Dict[str, Any], action: str,
                    value: Any = "") -> Dict[str, Any]:
    """Validate (action, value) for a device. The ONLY place commands are vetted.

    Returns {"ok": True, "payload": "<mqtt payload>"} on success, or
    {"ok": False, "error": "<code>", "allowed": [...]} on failure — the caller
    surfaces `allowed` and asks instead of guessing.
    """
    ctype = str(device.get("control_type", "")).strip().lower()
    meta = device.get("meta") or {}
    action = str(action or "").strip().lower()
    raw = str(value or "").strip().lower()

    if ctype == "switch":
        if action in _SWITCH_ACTIONS:
            return {"ok": True, "payload": action}
        return {"ok": False, "error": "bad_action", "allowed": sorted(_SWITCH_ACTIONS)}

    if ctype == "dimmer":
        if action in _SWITCH_ACTIONS:
            return {"ok": True, "payload": action}
        # "set"/"level" with a value, or the action itself being a number.
        lo = _coerce_int(meta.get("min", 0)) or 0
        hi = _coerce_int(meta.get("max", 100))
        hi = 100 if hi is None else hi
        level = _coerce_int(value if action in ("set", "level", "") else action)
        if level is not None:
            return {"ok": True, "payload": str(max(lo, min(hi, level)))}
        return {"ok": False, "error": "bad_value",
                "allowed": ["on", "off", f"{lo}..{hi}"]}

    if ctype == "media":
        chosen = action if action in _MEDIA_ACTIONS else raw
        if chosen in _MEDIA_ACTIONS:
            return {"ok": True, "payload": chosen}
        return {"ok": False, "error": "bad_action", "allowed": sorted(_MEDIA_ACTIONS)}

    if ctype == "cover":
        chosen = action if action in _COVER_ACTIONS else raw
        if chosen in _COVER_ACTIONS:
            return {"ok": True, "payload": chosen}
        return {"ok": False, "error": "bad_action", "allowed": sorted(_COVER_ACTIONS)}

    if ctype == "enum":
        values = [str(v).strip().lower() for v in (meta.get("values") or [])]
        chosen = raw if raw in values else (action if action in values else "")
        if chosen:
            return {"ok": True, "payload": chosen}
        return {"ok": False, "error": "bad_value", "allowed": values}

    if ctype == "ir":
        buttons = {str(k).strip().lower(): v for k, v in (meta.get("buttons") or {}).items()}
        btn = raw if raw in buttons else (action if action in buttons else "")
        if btn:
            # The MQTT payload is the learned code; the node replays it.
            return {"ok": True, "payload": str(buttons[btn]), "button": btn}
        return {"ok": False, "error": "not_learned", "allowed": sorted(buttons)}

    return {"ok": False, "error": "unknown_control_type", "allowed": sorted(CONTROL_TYPES)}


# ── Shaping ─────────────────────────────────────────────────────────────────

def _public(d: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": d.get("name", ""),
        "label": d.get("label", d.get("name", "")),
        "room": d.get("room", ""),
        "control_type": d.get("control_type", ""),
        "transport": d.get("transport", {}),
        "meta": d.get("meta", {}),
        "state": d.get("state", ""),
        "online": bool(d.get("online", False)),
        "last_seen": _iso(d.get("last_seen")),
    }


# ── CRUD ────────────────────────────────────────────────────────────────────

def list_devices() -> List[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return []
    return [_public(d) for d in coll.find({}).sort("name", 1)]


def get_device(name: str) -> Optional[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return None
    d = coll.find_one({"name": (name or "").strip().lower()})
    return d or None


def add_device(name: str, label: str, control_type: str,
               transport: Dict[str, Any], room: str = "",
               meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Register a new device. Validates name/type/transport; refuses duplicates."""
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        return {"ok": False, "error": "bad_name"}
    ctype = (control_type or "").strip().lower()
    if ctype not in CONTROL_TYPES:
        return {"ok": False, "error": "bad_control_type",
                "allowed": sorted(CONTROL_TYPES)}
    if not _valid_transport(transport):
        return {"ok": False, "error": "bad_transport"}
    if coll.find_one({"name": name}):
        return {"ok": False, "error": "exists"}
    coll.insert_one({
        "name": name,
        "label": (label or name).strip(),
        "room": (room or "").strip(),
        "control_type": ctype,
        "transport": transport,
        "meta": meta or {},
        "state": "",
        "online": False,
        "updated_at": _now(),
    })
    return {"ok": True, "name": name}


def update_device(name: str, **fields: Any) -> Dict[str, Any]:
    """Patch label/room/control_type/transport/meta. Unknown keys ignored."""
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    name = (name or "").strip().lower()
    update: Dict[str, Any] = {}
    if "label" in fields and str(fields["label"]).strip():
        update["label"] = str(fields["label"]).strip()
    if "room" in fields:
        update["room"] = str(fields["room"]).strip()
    if "control_type" in fields:
        ctype = str(fields["control_type"]).strip().lower()
        if ctype not in CONTROL_TYPES:
            return {"ok": False, "error": "bad_control_type",
                    "allowed": sorted(CONTROL_TYPES)}
        update["control_type"] = ctype
    if "transport" in fields:
        if not _valid_transport(fields["transport"]):
            return {"ok": False, "error": "bad_transport"}
        update["transport"] = fields["transport"]
    if "meta" in fields and isinstance(fields["meta"], dict):
        update["meta"] = fields["meta"]
    if not update:
        return {"ok": False, "error": "nothing_to_update"}
    update["updated_at"] = _now()
    r = coll.update_one({"name": name}, {"$set": update})
    if r.matched_count == 0:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "name": name}


def delete_device(name: str) -> Dict[str, Any]:
    """Delete a device the owner added."""
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    name = (name or "").strip().lower()
    r = coll.delete_one({"name": name})
    if r.deleted_count == 0:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "name": name}


def set_state(name: str, payload: str) -> None:
    """Record the last payload we sent to a device (best-effort, never raises)."""
    coll = _coll()
    if coll is None:
        return
    try:
        coll.update_one({"name": (name or "").strip().lower()},
                        {"$set": {"state": str(payload), "updated_at": _now()}})
    except Exception as e:  # noqa: BLE001
        logger.debug("[DeviceStore] set_state failed for %s: %s", name, e)


def set_online(name: str, online: bool) -> None:
    """Record a device heartbeat (best-effort) for the diagnosis layer."""
    coll = _coll()
    if coll is None:
        return
    try:
        coll.update_one(
            {"name": (name or "").strip().lower()},
            {"$set": {"online": bool(online), "last_seen": _now()}},
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("[DeviceStore] set_online failed for %s: %s", name, e)


def learn_ir_button(name: str, button: str, code: str) -> Dict[str, Any]:
    """Store a learned IR code under a button name for an `ir` device."""
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    d = get_device(name)
    if d is None:
        return {"ok": False, "error": "not_found"}
    if d.get("control_type") != "ir":
        return {"ok": False, "error": "not_ir"}
    button = (button or "").strip().lower()
    if not button or not str(code).strip():
        return {"ok": False, "error": "bad_button"}
    meta = d.get("meta") or {}
    buttons = dict(meta.get("buttons") or {})
    buttons[button] = str(code).strip()
    meta["buttons"] = buttons
    coll.update_one({"name": d["name"]},
                    {"$set": {"meta": meta, "updated_at": _now()}})
    return {"ok": True, "name": d["name"], "button": button}


def _valid_transport(transport: Any) -> bool:
    if not isinstance(transport, dict):
        return False
    kind = str(transport.get("kind", "")).strip().lower()
    if kind == "mqtt":
        return bool(str(transport.get("topic", "")).strip())
    if kind == "wifi_api":
        return bool(str(transport.get("url", "")).strip())
    return False
