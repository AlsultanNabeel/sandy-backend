"""Room scenes — named automations described as a list of actions (data).

A scene is a label + a list of actions. Starting a focus mode
(study/read/relax/sleep/movie/brainstorm/morning) applies its scene; ending it
applies the `off` scene. Scenes live in Mongo so the owner can customise every
mode's behaviour from the web. The built-in set is seeded once on first boot
and flagged `builtin` (resettable, not deletable).

Collection: sandy_scenes
  {_id, name, label, icon, actions: [{device, value}], builtin, updated_at}

This is a pure data store: `apply_scene` no longer actuates any hardware —
it returns the scene's stored action list so an app (e.g. iPhone Shortcuts)
can execute it. `actions` use the device vocabulary
(light/color/music/fan/curtain) defined locally below.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.utils.user_profiles import active_profile_allows_privileged_access

# Scene action vocabulary (data only — nothing here drives hardware).
VALID_DEVICES = frozenset({"light", "color", "music", "fan", "curtain", "scene"})
_VALID_COLOR = {"warm", "cool", "white", "red", "green", "blue", "purple", "amber"}


def normalize_action(device: str, value: str) -> Optional[str]:
    """Return a clean payload for (device, value), or None if invalid.

    Light/fan accept on|off or a 0..100 brightness/speed; color accepts a named
    color or #rrggbb; music accepts on|off|pause; curtain open|close.
    """
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
_TIMERS = "sandy_scene_timers"   # timed reverts: {fire_at, device, value}
_mongo_db = None

# name → (label, icon, default actions). Seeded once; the owner can edit freely.
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
    global _mongo_db
    _mongo_db = mongo_db
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index("name", unique=True, background=True)
        mongo_db[_TIMERS].create_index("fire_at", background=True)
        _seed_builtins()
        print("[SceneStore] ready")
    except Exception as e:  # noqa: BLE001
        print(f"[SceneStore] index skipped: {e}")


def _require_owner() -> None:
    if not active_profile_allows_privileged_access():
        raise PermissionError("هذا خاص بنبيل 😊")


def _now():
    return datetime.now(timezone.utc)


def _seed_builtins() -> None:
    """Insert any built-in scene that doesn't exist yet (idempotent)."""
    if _mongo_db is None:
        return
    for name, spec in _BUILTIN.items():
        if _mongo_db[_COLL].find_one({"name": name}) is None:
            _mongo_db[_COLL].insert_one({
                "name": name,
                "label": spec["label"],
                "icon": spec["icon"],
                "actions": spec["actions"],
                "builtin": True,
                "updated_at": _now(),
            })


def _clean_actions(actions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Keep only valid, normalized actions.

    An action is {device, value} plus two optional timing fields:
      for_min — run `value` now, then auto-revert after N minutes
      then    — what to send on revert (default "off"); normalized per device
    e.g. {device: music, value: on, for_min: 30}  → music on, off after 30 min.
    """
    out: List[Dict[str, Any]] = []
    for a in actions or []:
        dev = str(a.get("device", "")).strip().lower()
        payload = normalize_action(dev, a.get("value", ""))
        if dev not in VALID_DEVICES or payload is None:
            continue
        item: Dict[str, Any] = {"device": dev, "value": payload}
        try:
            for_min = int(a.get("for_min", 0) or 0)
        except (TypeError, ValueError):
            for_min = 0
        if for_min > 0:
            then = normalize_action(dev, a.get("then", "off")) or "off"
            item["for_min"] = min(720, for_min)
            item["then"] = then
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
    _require_owner()
    if _mongo_db is None:
        return []
    return [_public(d) for d in _mongo_db[_COLL].find().sort("builtin", -1)]


def get_scene(name: str) -> Optional[Dict[str, Any]]:
    if _mongo_db is None:
        return None
    d = _mongo_db[_COLL].find_one({"name": (name or "").strip().lower()})
    return _public(d) if d else None


def set_scene_actions(name: str, actions: List[Dict[str, str]]) -> Dict[str, Any]:
    """Customise what a scene does to the room. Works for built-ins too."""
    _require_owner()
    if _mongo_db is None:
        return {"ok": False}
    name = (name or "").strip().lower()
    if not name:
        return {"ok": False, "error": "empty_name"}
    _mongo_db[_COLL].update_one(
        {"name": name},
        {"$set": {"actions": _clean_actions(actions), "updated_at": _now()}},
    )
    return {"ok": True, "name": name}


def add_scene(name: str, label: str = "", icon: str = "🎛️",
              actions: Optional[List[Dict[str, str]]] = None) -> Dict[str, Any]:
    _require_owner()
    if _mongo_db is None:
        return {"ok": False}
    name = (name or "").strip().lower()
    if not name:
        return {"ok": False, "error": "empty_name"}
    if _mongo_db[_COLL].find_one({"name": name}):
        return {"ok": False, "error": "exists"}
    _mongo_db[_COLL].insert_one({
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
    _require_owner()
    if _mongo_db is None:
        return {"ok": False}
    name = (name or "").strip().lower()
    d = _mongo_db[_COLL].find_one({"name": name})
    if not d:
        return {"ok": False, "error": "not_found"}
    if d.get("builtin") and name in _BUILTIN:
        _mongo_db[_COLL].update_one(
            {"name": name},
            {"$set": {"actions": _BUILTIN[name]["actions"], "updated_at": _now()}},
        )
        return {"ok": True, "reset": True, "name": name}
    _mongo_db[_COLL].delete_one({"name": name})
    return {"ok": True, "deleted": True, "name": name}


def apply_scene(name: str) -> Dict[str, Any]:
    """Return a scene's stored actions (data) for an app to execute.

    No hardware is actuated — the action list is returned as-is so a caller
    (e.g. iPhone Shortcuts) can run it. Re-applying any scene cancels timed
    reverts still pending from the previous one, then schedules this scene's
    own `for_min` reverts as data.
    """
    _require_owner()
    sc = get_scene(name)
    if not sc:
        return {"ok": False, "error": "not_found"}

    timers = 0
    if _mongo_db is not None:
        _mongo_db[_TIMERS].delete_many({})   # new scene supersedes old reverts
        now = _now()
        docs = [
            {"fire_at": now + timedelta(minutes=a["for_min"]),
             "device": a["device"], "value": a["then"]}
            for a in sc["actions"] if a.get("for_min")
        ]
        if docs:
            _mongo_db[_TIMERS].insert_many(docs)
            timers = len(docs)
    return {
        "ok": True,
        "name": sc["name"],
        "label": sc["label"],
        "timers": timers,
        "actions": sc["actions"],
    }


def run_due_timers() -> List[Dict[str, str]]:
    """Return any timed reverts whose moment has come. Call every minute.

    Returns the due revert actions as data (a list of {device, value}) and
    clears them from the store; a caller can hand them to an app to execute.
    Runs without an owner check — it's a scheduler job acting on the owner's
    own scene timers, not a user-facing entry point.
    """
    if _mongo_db is None:
        return []
    due: List[Dict[str, str]] = []
    for t in list(_mongo_db[_TIMERS].find({"fire_at": {"$lte": _now()}})):
        due.append({"device": t.get("device", ""), "value": t.get("value", "")})
        _mongo_db[_TIMERS].delete_one({"_id": t["_id"]})
    return due
