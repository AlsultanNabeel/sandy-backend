"""Room scenes (sandy_scenes): a label plus a list of {device, value} actions.

Built-ins are seeded per user and resettable, not deletable. apply_scene sends
each action to the owner's registered devices and also returns the list.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.utils.tenant_db import scoped
from app.db import configure, get_db

logger = logging.getLogger(__name__)

# Legacy room vocabulary for scene actions.
VALID_DEVICES = frozenset({"light", "color", "music", "fan", "curtain", "scene"})
_VALID_COLOR = {"warm", "cool", "white", "red", "green", "blue", "purple", "amber"}


def normalize_action(device: str, value: str) -> Optional[str]:
    """Clean payload for (device, value), or None if invalid."""
    device = (device or "").strip().lower()
    value = str(value or "").strip().lower()
    if device not in VALID_DEVICES or not value:
        return None
    if device in ("light", "fan"):
        if value in ("on", "off"):
            return value
        try:
            return str(max(0, min(100, int(value))))
        except ValueError:
            return None
    if device == "color":
        if value in _VALID_COLOR:
            return value
        if value.startswith("#") and len(value) == 7:
            return value
        return None
    if device == "music":
        return value if value in ("on", "off", "pause") else None
    if device == "curtain":
        return value if value in ("open", "close") else None
    if device == "scene":
        return value
    return None

_COLL = "sandy_scenes"

# سقف أمان، مش حد منتج.
MAX_SCENES = 200
MAX_DUE_TIMERS = 100
MAX_TIMER_TRIES = 5
_TIMERS = "sandy_scene_timers"   # timed reverts: {fire_at, device, value, tries}

# Seeded once per user; the owner can edit freely.
_BUILTIN: Dict[str, Dict[str, Any]] = {
    "study":      {"label": "دراسة",     "icon": "📚", "actions": [
        {"device": "light", "value": "85"}, {"device": "color", "value": "cool"},
        {"device": "music", "value": "off"}, {"device": "fan", "value": "on"},
        {"device": "curtain", "value": "open"}]},
    "read":       {"label": "قراءة",     "icon": "📖", "actions": [
        {"device": "light", "value": "60"}, {"device": "color", "value": "warm"},
        {"device": "music", "value": "off"}]},
    "brainstorm": {"label": "عصف ذهني",  "icon": "💡", "actions": [
        {"device": "light", "value": "90"}, {"device": "color", "value": "white"},
        {"device": "music", "value": "on"}]},
    "relax":      {"label": "راحة",      "icon": "🌙", "actions": [
        {"device": "light", "value": "35"}, {"device": "color", "value": "warm"},
        {"device": "music", "value": "on"}]},
    "movie":      {"label": "فيلم",      "icon": "🎬", "actions": [
        {"device": "light", "value": "10"}, {"device": "color", "value": "blue"},
        {"device": "music", "value": "off"}, {"device": "curtain", "value": "close"}]},
    "sleep":      {"label": "نوم",       "icon": "😴", "actions": [
        {"device": "light", "value": "off"}, {"device": "music", "value": "off"},
        {"device": "fan", "value": "on"}, {"device": "curtain", "value": "close"}]},
    "morning":    {"label": "صباح",      "icon": "☀️", "actions": [
        {"device": "light", "value": "100"}, {"device": "curtain", "value": "open"},
        {"device": "music", "value": "on"}]},
    "off":        {"label": "إطفاء",     "icon": "⏻", "actions": [
        {"device": "light", "value": "off"}, {"device": "music", "value": "off"},
        {"device": "fan", "value": "off"}]},
}


def init_scene_store(mongo_db) -> None:
    configure(mongo_db)
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index(
            [("user_id", 1), ("name", 1)], unique=True, background=True
        )
        mongo_db[_TIMERS].create_index(
            [("user_id", 1), ("fire_at", 1)], background=True
        )
        logger.info("[SceneStore] ready")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[SceneStore] index skipped: {e}")


def _coll():
    return scoped(get_db(), _COLL)


def _timers():
    return scoped(get_db(), _TIMERS)


def _now():
    return datetime.now(timezone.utc)


def _seed_builtins() -> None:
    coll = _coll()
    if coll is None:
        return
    for name, spec in _BUILTIN.items():
        if coll.find_one({"name": name}) is None:
            coll.insert_one({
                "name": name,
                "label": spec["label"],
                "icon": spec["icon"],
                "actions": spec["actions"],
                "builtin": True,
                "updated_at": _now(),
            })


def _clean_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only valid actions.

    An action is {device, value} plus optional `for_min` (revert after N minutes)
    and `then` (revert value, default "off"). `device` is a registry device name
    (validated on apply) or a legacy room word (normalized here).
    """
    out: List[Dict[str, Any]] = []
    for a in actions or []:
        dev = str(a.get("device", "")).strip().lower()
        raw_val = str(a.get("value", "")).strip()
        if not dev or not raw_val:
            continue
        if dev in VALID_DEVICES:
            payload = normalize_action(dev, raw_val)
            if payload is None:
                continue
        else:
            payload = raw_val
        item: Dict[str, Any] = {"device": dev, "value": payload}
        try:
            for_min = int(a.get("for_min", 0) or 0)
        except (TypeError, ValueError):
            for_min = 0
        if for_min > 0:
            raw_then = str(a.get("then", "off")).strip() or "off"
            then = normalize_action(dev, raw_then) if dev in VALID_DEVICES else raw_then
            item["for_min"] = min(720, for_min)
            item["then"] = then or "off"
        out.append(item)
    return out


def _public(d: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": d.get("name", ""),
        "label": d.get("label", d.get("name", "")),
        "icon": d.get("icon", "🎛️"),
        "actions": d.get("actions", []),
        "builtin": bool(d.get("builtin", False)),
    }


def list_scenes() -> List[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return []
    _seed_builtins()
    return [_public(d) for d in coll.find({}).sort("builtin", -1).limit(MAX_SCENES)]


def get_scene(name: str) -> Optional[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return None
    _seed_builtins()
    d = coll.find_one({"name": (name or "").strip().lower()})
    return _public(d) if d else None


def set_scene_actions(name: str, actions: List[Dict[str, str]]) -> Dict[str, Any]:
    """Works for built-ins too."""
    coll = _coll()
    if coll is None:
        return {"ok": False}
    name = (name or "").strip().lower()
    if not name:
        return {"ok": False, "error": "empty_name"}
    coll.update_one(
        {"name": name},
        {"$set": {"actions": _clean_actions(actions), "updated_at": _now()}},
    )
    return {"ok": True, "name": name}


def add_scene(name: str, label: str = "", icon: str = "🎛️",
              actions: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    coll = _coll()
    if coll is None:
        return {"ok": False}
    name = (name or "").strip().lower()
    if not name:
        return {"ok": False, "error": "empty_name"}
    if coll.find_one({"name": name}):
        return {"ok": False, "error": "exists"}
    coll.insert_one({
        "name": name,
        "label": (label or name).strip(),
        "icon": (icon or "🎛️").strip(),
        "actions": _clean_actions(actions or []),
        "builtin": False,
        "updated_at": _now(),
    })
    return {"ok": True, "name": name}


def delete_scene(name: str) -> Dict[str, Any]:
    """Delete a custom scene; built-ins are reset to defaults instead."""
    coll = _coll()
    if coll is None:
        return {"ok": False}
    name = (name or "").strip().lower()
    d = coll.find_one({"name": name})
    if not d:
        return {"ok": False, "error": "not_found"}
    if d.get("builtin") and name in _BUILTIN:
        coll.update_one(
            {"name": name},
            {"$set": {"actions": _BUILTIN[name]["actions"], "updated_at": _now()}},
        )
        return {"ok": True, "reset": True, "name": name}
    coll.delete_one({"name": name})
    return {"ok": True, "deleted": True, "name": name}


def apply_scene(name: str) -> Dict[str, Any]:
    """Run a scene on the owner's devices and return its actions (callers like Shortcuts may run them).

    Re-applying any scene cancels pending reverts and schedules this scene's `for_min` ones.
    """
    sc = get_scene(name)
    if not sc:
        return {"ok": False, "error": "not_found"}

    timers = 0
    tcoll = _timers()
    if tcoll is not None:
        tcoll.delete_many({})
        now = _now()
        docs = [
            {"fire_at": now + timedelta(minutes=a["for_min"]),
             "device": a["device"], "value": a["then"]}
            for a in sc["actions"] if a.get("for_min")
        ]
        if docs:
            tcoll.insert_many(docs)
            timers = len(docs)
    sent, missed = _actuate(sc["actions"])

    return {
        "ok": True,
        "name": sc["name"],
        "label": sc["label"],
        "timers": timers,
        "sent": sent,
        "missed": missed,
        "actions": sc["actions"],
    }


def _actuate(actions: List[Dict[str, Any]]) -> tuple:
    """Send each action to its device; returns (sent, names that were missed)."""
    from app.features.device_store import (
        command_payload, device_topic, get_devices, set_state,
    )
    from app.integrations.room_device import get_room_device_client

    sent, missed = 0, []
    # Every device the scene names, in one read.
    try:
        devices = get_devices([str(a.get("device") or "") for a in actions or []])
    except Exception as exc:  # noqa: BLE001
        logger.debug("[SceneStore] device lookup failed: %s", exc)
        devices = {}
    for a in actions or []:
        name = str(a.get("device") or "").strip().lower()
        value = str(a.get("value") or "").strip()
        if not name:
            continue
        try:
            device = devices.get(name)
            if device is None:
                missed.append(name)
                continue
            # Same validation gate as the device tool.
            res = command_payload(device, value, value)
            if not res.get("ok"):
                res = command_payload(device, "set", value)
            if not res.get("ok"):
                missed.append(name)
                continue
            payload = res["payload"]
            if get_room_device_client().send_to_topic(device_topic(device), payload):
                set_state(name, payload)
                sent += 1
            else:
                missed.append(name)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[SceneStore] %s failed: %s", name, exc)
            missed.append(name)
    return sent, missed


def run_due_timers() -> Dict[str, Any]:
    """Fire the active user's due reverts, each claimed by an atomic find-and-delete.

    Missed ones are retried a minute later, up to MAX_TIMER_TRIES.
    """
    tcoll = _timers()
    if tcoll is None:
        return {"due": [], "sent": 0, "missed": []}
    due: List[Dict[str, str]] = []
    # Capped per tick; the rest stay for the next one.
    for _ in range(MAX_DUE_TIMERS):
        t = tcoll.find_one_and_delete({"fire_at": {"$lte": _now()}},
                                      sort=[("fire_at", 1)])
        if not t:
            break
        due.append({"device": t.get("device", ""), "value": t.get("value", ""),
                    "tries": int(t.get("tries") or 0)})
    if not due:
        return {"due": [], "sent": 0, "missed": []}
    sent, missed = _actuate(due)
    retry = []
    for a in due:
        name = str(a["device"]).strip().lower()
        if name in missed and a["tries"] + 1 < MAX_TIMER_TRIES:
            retry.append({"fire_at": _now() + timedelta(minutes=1),
                          "device": a["device"], "value": a["value"],
                          "tries": a["tries"] + 1})
    if retry:
        tcoll.insert_many(retry)
    return {"due": due, "sent": sent, "missed": missed, "retrying": len(retry)}


def users_with_due_timers(mongo_db, limit: int = 500) -> List[str]:
    """Owners with a revert due now (raw cross-tenant read; only ids leave)."""
    if mongo_db is None:
        return []
    try:
        ids = mongo_db[_TIMERS].distinct("user_id", {"fire_at": {"$lte": _now()}})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[SceneStore] due-timer scan failed: %s", exc)
        return []
    return [str(u) for u in ids if u][:limit]
