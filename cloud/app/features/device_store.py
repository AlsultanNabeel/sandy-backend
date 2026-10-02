"""Device registry — per-tenant controllable devices as data, not code.

Only registered devices with validated actions can be actuated; unknown ones are
refused, never guessed. Pure data + validation: ``command_payload`` returns the
payload, the caller sends it. Collection ``sandy_devices``: name (slug), label,
room, control_type, transport ({"kind": "node", node_id, output} or
{"kind": "mqtt", topic}), meta, state, online, last_seen, updated_at.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pymongo.errors import PyMongoError

from app.utils.tenant_db import scoped
from app.db import configure, get_db

logger = logging.getLogger(__name__)

_COLL = "sandy_devices"

# Safety cap, not a product limit.
MAX_DEVICES = 500

# switch: on|off · dimmer: on|off|int in meta.min..max · enum: meta.values ·
# media: on|off|pause · cover: open|close|stop · ir: learned meta.buttons · text: free text
CONTROL_TYPES = frozenset({"switch", "dimmer", "enum", "media", "cover", "ir", "text"})

_MEDIA_ACTIONS = {"on", "off", "pause"}
_COVER_ACTIONS = {"open", "close", "stop"}
_SWITCH_ACTIONS = {"on", "off"}

_NAME_RE = re.compile(r"^[a-z0-9_]{1,40}$")


def init_device_store(mongo_db) -> None:
    configure(mongo_db)
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
    return scoped(get_db(), _COLL)


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
    """Validate (action, value) for a device — the only place commands are vetted.

    {"ok": True, "payload": ...} or {"ok": False, "error": code, "allowed": [...]}.
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

    if ctype == "text":
        # Free text: not lower-cased or matched against a list.
        text = str(value if value not in (None, "") else action)
        text = text.strip()
        if text.lower() in ("dismiss", "clear", ""):
            return {"ok": True, "payload": "dismiss"}
        # Bytes, not chars: the firmware buffer is 256 bytes and Arabic is multi-byte.
        limit = _coerce_int(meta.get("max_bytes", 255)) or 255
        if len(text.encode("utf-8")) > limit:
            return {"ok": False, "error": "too_long", "allowed": [f"<= {limit} bytes"]}
        text = text.replace("\n", " ").replace("\r", " ")
        return {"ok": True, "payload": "text:" + text}

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
    return [_public(d) for d in coll.find({}).sort("name", 1).limit(MAX_DEVICES)]


def get_device(name: str) -> Optional[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return None
    d = coll.find_one({"name": (name or "").strip().lower()})
    return d or None


def get_devices(names: List[str]) -> Dict[str, Dict[str, Any]]:
    """Several devices by name in one query, keyed by name (missing ones absent)."""
    coll = _coll()
    wanted = sorted({(n or "").strip().lower() for n in names if (n or "").strip()})
    if coll is None or not wanted:
        return {}
    return {d["name"]: d for d in coll.find({"name": {"$in": wanted}}).limit(len(wanted))}


def add_device(name: str, label: str, control_type: str,
               transport: Dict[str, Any], room: str = "",
               meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
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
    if not _transport_owned(transport):
        return {"ok": False, "error": "node_not_paired"}
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
        if not _transport_owned(fields["transport"]):
            return {"ok": False, "error": "node_not_paired"}
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
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_store"}
    name = (name or "").strip().lower()
    r = coll.delete_one({"name": name})
    if r.deleted_count == 0:
        return {"ok": False, "error": "not_found"}
    return {"ok": True, "name": name}


def set_state(name: str, payload: str) -> None:
    """Record the last payload sent (best-effort, never raises)."""
    coll = _coll()
    if coll is None:
        return
    try:
        coll.update_one({"name": (name or "").strip().lower()},
                        {"$set": {"state": str(payload), "updated_at": _now()}})
    except Exception as e:  # noqa: BLE001
        logger.debug("[DeviceStore] set_state failed for %s: %s", name, e)


# What a scene can put back: a learned IR code toggles and a screen's text is a message,
# so neither is replayed.
_NOT_RESTORED = ("ir", "text")


def keep_before_scene(names: List[str]) -> None:
    """Remember these devices' state as it is now (`before_scene`), dropping the last
    scene's, so «رجّعي الغرفة زي ما كانت» can put it back."""
    coll = _coll()
    if coll is None:
        return
    coll.update_many({"before_scene": {"$exists": True}}, {"$unset": {"before_scene": ""}})
    for name, d in get_devices(names).items():
        if d.get("state") and d.get("control_type") not in _NOT_RESTORED:
            coll.update_one({"name": name}, {"$set": {"before_scene": d["state"]}})


def take_before_scene() -> List[Dict[str, str]]:
    """The kept states as scene actions ({device, value}), forgotten once taken."""
    coll = _coll()
    if coll is None:
        return []
    kept = [{"device": d["name"], "value": d["before_scene"]}
            for d in coll.find({"before_scene": {"$exists": True}}).limit(MAX_DEVICES)]
    coll.update_many({"before_scene": {"$exists": True}}, {"$unset": {"before_scene": ""}})
    return kept


def learn_ir_button(name: str, button: str, code: str) -> Dict[str, Any]:
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


def delete_devices_for_node(node_id: str) -> int:
    """Remove this tenant's devices that go through a node (on unpair)."""
    coll = _coll()
    node_id = (node_id or "").strip()
    if coll is None or not node_id:
        return 0
    try:
        r = coll.delete_many({"transport.kind": "node",
                              "transport.node_id": node_id})
        return int(getattr(r, "deleted_count", 0) or 0)
    except PyMongoError as exc:
        logger.warning("[device_store] releasing devices for %s failed: %s",
                       node_id, exc)
        return 0


def device_topic(device: Dict[str, Any]) -> Optional[str]:
    """MQTT topic for a device, from its transport."""
    t = device.get("transport") or {}
    kind = str(t.get("kind", "")).strip().lower()
    if kind == "mqtt":
        return str(t.get("topic", "")).strip() or None
    if kind == "node":
        node_id = str(t.get("node_id", "")).strip()
        output = str(t.get("output", "")).strip()
        if node_id and output:
            return f"sandy/node/{node_id}/{output}"
    return None


def _topic_query(topic: str) -> Dict[str, Any]:
    """device_topic() run backwards, so ownership is one indexed lookup.

    If the two ever disagree the actuation is refused (a test pins them equal).
    """
    if topic.startswith("sandy/node/"):
        rest = topic[len("sandy/node/"):]
        node_id, _, output = rest.partition("/")
        if not node_id or not output:
            return {"_id": {"$exists": False}}   # can match nothing
        return {"transport.kind": "node",
                "transport.node_id": node_id,
                "transport.output": output}
    return {"transport.kind": "mqtt", "transport.topic": topic}


def tenant_owns_topic(topic: str) -> bool:
    """True when ``topic`` actuates a device of the current tenant (the scoped read is the check)."""
    coll = _coll()
    if coll is None:
        return False
    topic = (topic or "").strip()
    if not topic:
        return False
    try:
        return coll.find_one(_topic_query(topic), {"_id": 1}) is not None
    except Exception as e:  # noqa: BLE001 — a lookup failure must not actuate
        logger.warning("[DeviceStore] ownership check failed for %s: %s", topic, e)
        return False


def _valid_transport(transport: Any) -> bool:
    if not isinstance(transport, dict):
        return False
    kind = str(transport.get("kind", "")).strip().lower()
    if kind == "mqtt":
        topic = str(transport.get("topic", "")).strip()
        # sandy/node/... is reserved for the ownership-checked "node" transport.
        return bool(topic) and not topic.startswith("sandy/node/")
    if kind == "node":
        return bool(str(transport.get("node_id", "")).strip()) and bool(
            str(transport.get("output", "")).strip()
        )
    if kind == "wifi_api":
        return bool(str(transport.get("url", "")).strip())
    return False


def _transport_owned(transport: Any) -> bool:
    """A ``node`` transport must point at a node this tenant paired."""
    t = transport if isinstance(transport, dict) else {}
    if str(t.get("kind", "")).strip().lower() != "node":
        return True
    node_id = str(t.get("node_id", "")).strip()
    if not node_id:
        return False
    try:
        from app.features import node_store
        return node_store.get_node(node_id) is not None
    except Exception as e:  # noqa: BLE001
        logger.warning("[DeviceStore] node ownership check failed: %s", e)
        return False
