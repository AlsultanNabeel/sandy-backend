"""Room scenes (sandy_scenes): a label plus a list of {device, value} actions.

Built-ins are seeded per user and resettable, not deletable. apply_scene sends
each action to the owner's registered devices and also returns the list. An action
names a device of the registry, or one of the room words scenes were written in
before devices were rows (`_LEGACY`), which is read as the device on that output.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.blocks import _base, schedules
from app.db import configure, get_db
from app.utils.tenant_db import scoped

logger = logging.getLogger(__name__)

# The room words the built-ins and the scenes saved before devices were rows still use:
# the output each means (None: no board has it) and what to call it when it is passed over.
_LEGACY: Dict[str, tuple] = {
    "light":   ("room/light", "ضو الغرفة"),
    "music":   ("room/music", "موسيقى الغرفة"),
    "buzzer":  ("buzzer", "جرس ساندي"),
    "color":   (None, "لون الإضاءة"),
    "fan":     (None, "المروحة"),
    "curtain": (None, "الستارة"),
    "scene":   (None, "مشهد الغرفة"),
}
# A player with no on/off of its own (the room's music): «on» resumes, «off» stops.
_PLAYER_WORDS = {"on": "resume", "off": "stop"}

_COLL = "sandy_scenes"

# سقف أمان، مش حد منتج.
MAX_SCENES = 200
# A revert the device misses is retried a minute later, this many times in all.
MAX_TIMER_TRIES = 5

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
        logger.info("[SceneStore] ready")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[SceneStore] index skipped: {e}")


def _coll():
    return scoped(get_db(), _COLL)


# A scene's own reverts; a timed device command the user asked for («طفّي المكيف بعد
# ساعة», `payload.asked`) is not the scene's to cancel.
_SCENE_TIMERS = {"kind": "scene", "status": "pending", "payload.asked": {"$ne": True}}


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
    and `then` (revert value, default "off"). `device` is a registry device name or
    a legacy room word; the value is validated on apply, against the device itself.
    """
    out: List[Dict[str, Any]] = []
    for a in actions or []:
        dev = str(a.get("device", "")).strip().lower()
        payload = str(a.get("value", "")).strip()
        if not dev or not payload:
            continue
        item: Dict[str, Any] = {"device": dev, "value": payload}
        try:
            for_min = int(a.get("for_min", 0) or 0)
        except (TypeError, ValueError):
            for_min = 0
        if for_min > 0:
            item["for_min"] = min(720, for_min)
            item["then"] = str(a.get("then", "off")).strip() or "off"
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
    """Every scene, its room words shown as the devices they mean (so the editor shows
    and saves real devices); a word no device answers to is left as it is."""
    coll = _coll()
    if coll is None:
        return []
    _seed_builtins()
    targets = _legacy_targets()
    out = []
    for d in coll.find({}).sort("builtin", -1).limit(MAX_SCENES):
        sc = _public(d)
        sc["actions"] = [_as_device(a, targets) for a in sc["actions"]]
        out.append(sc)
    return out


def _as_device(action: Dict[str, Any], targets: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    device = targets.get(str(action.get("device") or "").strip().lower())
    if device is None:
        return action
    shown = {**action, "device": device["name"],
             "value": _value_for(device, str(action.get("value") or ""))}
    if "then" in action:
        shown["then"] = _value_for(device, str(action["then"]))
    return shown


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

    Re-applying any scene cancels pending reverts and schedules this scene's `for_min`
    ones as `scene` rows in sandy_schedules, which the schedule runner fires.
    """
    sc = get_scene(name)
    if not sc:
        return {"ok": False, "error": "not_found"}

    resolved, skipped, unknown = _resolve(sc["actions"])
    timers = 0
    pending = _base.coll(_base.SCHEDULES)
    if pending is not None:
        pending.update_many(_SCENE_TIMERS,
                            {"$set": {"status": "cancelled"}})
        now = _now()
        for a in sc["actions"]:
            if a.get("for_min") and schedules.add(
                    "scene", f"{a['device']} → {a['then']}",
                    now + timedelta(minutes=a["for_min"]),
                    {"device": a["device"], "value": a["then"]}):
                timers += 1
    from app.features.device_store import keep_before_scene

    keep_before_scene([device["name"] for device, _ in resolved])
    r = _send(resolved)

    return {
        "ok": True,
        "name": sc["name"],
        "label": sc["label"],
        "timers": timers,
        **r,
        "missed": unknown + r["missed"],
        "skipped": skipped,
        "actions": sc["actions"],
    }


def restore_room() -> Dict[str, Any]:
    """Puts the devices the last scene changed back as they were, and drops its timers."""
    from app.features.device_store import take_before_scene

    actions = take_before_scene()
    if not actions:
        return {"ok": False, "error": "nothing_kept"}
    pending = _base.coll(_base.SCHEDULES)
    if pending is not None:
        pending.update_many(_SCENE_TIMERS,
                            {"$set": {"status": "cancelled"}})
    return {"ok": True, **_actuate(actions)}


def _legacy_targets() -> Dict[str, Dict[str, Any]]:
    """Each room word that one device of this tenant answers to (its output), by word.
    Two robots with a room each is a guess, so a word with several devices is left out."""
    from app.features.device_store import devices_on_output

    targets = {}
    for word, (output, _label) in _LEGACY.items():
        hits = devices_on_output(output) if output else []
        if len(hits) == 1:
            targets[word] = hits[0]
    return targets


def _value_for(device: Dict[str, Any], value: str) -> str:
    """A value written for the room words, as this device takes it: a level on a switch
    is on or off (the room light is a servo pressing the wall switch), and a player with
    no on/off resumes or stops."""
    v = value.strip().lower()
    ctype = device.get("control_type")
    if ctype == "switch" and v.isdigit():
        return "on" if int(v) > 0 else "off"
    values = {str(x).lower() for x in (device.get("meta") or {}).get("values") or []}
    if ctype == "enum" and v in _PLAYER_WORDS and v not in values and _PLAYER_WORDS[v] in values:
        return _PLAYER_WORDS[v]
    return value.strip()


def _resolve(actions: List[Dict[str, Any]]) -> tuple:
    """(each action as [device, value], room words no device answers to, by their Arabic
    name, names that are not a device)."""
    from app.features.device_store import get_devices

    names = [str(a.get("device") or "").strip().lower() for a in actions or []]
    targets = _legacy_targets() if any(n in _LEGACY for n in names) else {}
    try:
        devices = get_devices([n for n in names if n not in _LEGACY])
    except Exception as exc:  # noqa: BLE001
        logger.debug("[SceneStore] device lookup failed: %s", exc)
        devices = {}
    resolved, skipped, unknown = [], [], []
    for name, a in zip(names, actions or []):
        if not name:
            continue
        device = targets.get(name) if name in _LEGACY else devices.get(name)
        if device is None:
            if name in _LEGACY:
                skipped.append(_LEGACY[name][1])
            else:
                unknown.append(name)
            continue
        resolved.append([device, _value_for(device, str(a.get("value") or ""))])
    return resolved, list(dict.fromkeys(skipped)), unknown


def _actuate(actions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Send each action to its device: {sent, missed (not reached or not a device),
    offline (labels of the devices whose board is gone), skipped (room words no device
    answers to)}. Whatever cannot go is passed over; the rest still go."""
    resolved, skipped, unknown = _resolve(actions)
    r = _send(resolved)
    return {**r, "missed": unknown + r["missed"], "skipped": skipped}


def _send(resolved: List[list]) -> Dict[str, Any]:
    """Send each [device, value]; {sent, missed (labels), offline (labels)}."""
    from app.features.device_store import command_payload, device_topic, set_state
    from app.integrations.room_device import get_room_device_client

    sent, missed, offline = 0, [], []
    for device, value in resolved:
        label = device.get("label") or device["name"]
        try:
            # Same validation gate as the device tool.
            res = command_payload(device, value, value)
            if not res.get("ok"):
                res = command_payload(device, "set", value)
            if not res.get("ok"):
                missed.append(label)
                continue
            payload = res["payload"]
            if device.get("board_gone"):
                offline.append(label)
                continue
            if get_room_device_client().send_to_topic(device_topic(device), payload):
                set_state(device["name"], payload)
                sent += 1
            else:
                missed.append(label)
        except Exception as exc:  # noqa: BLE001
            logger.debug("[SceneStore] %s failed: %s", device.get("name"), exc)
            missed.append(label)
    return {"sent": sent, "missed": missed, "offline": offline}
