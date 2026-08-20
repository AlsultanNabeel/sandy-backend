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

Tenant isolation is enforced by the scoped() layer: _coll()/_timers() return
None when there's no Mongo handle or no active tenant, and user_id is injected
on every read/write so each user only ever sees and seeds their own scenes.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.utils.tenant_db import scoped
from app.db import configure, get_db
import logging

logger = logging.getLogger(__name__)

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

# سقف أمان، مش حد منتج — ما حدا بيوصله بالاستعمال العادي. موجود عشان
# خلل بالكتابة أو حساب دخل عليه إشي غريب ما يتحوّل لنداء بيسحب المجموعة
# كلها ويوقّع الطلب.
MAX_SCENES = 200
MAX_DUE_TIMERS = 100
_TIMERS = "sandy_scene_timers"   # timed reverts: {fire_at, device, value}

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
    """Tenant-scoped scenes collection, or None when no db / no active tenant."""
    return scoped(get_db(), _COLL)


def _timers():
    """Tenant-scoped scene-timers collection, or None when no db / no tenant."""
    return scoped(get_db(), _TIMERS)


def _now():
    return datetime.now(timezone.utc)


def _seed_builtins() -> None:
    """Insert any built-in scene this user doesn't have yet (idempotent)."""
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
    """Keep only valid, normalized actions.

    An action is {device, value} plus two optional timing fields:
      for_min — run `value` now, then auto-revert after N minutes
      then    — what to send on revert (default "off")
    e.g. {device: music, value: on, for_min: 30}  → music on, off after 30 min.

    `device` may be a **registry device name** (validated at apply time) or a legacy
    room-vocab device (light/color/music/fan/curtain, normalized here for back-compat).
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
            payload = raw_val  # registry device — validated against the registry on apply
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
    _seed_builtins()   # ensure this user has the default set
    return [_public(d) for d in coll.find({}).sort("builtin", -1).limit(MAX_SCENES)]


def get_scene(name: str) -> Optional[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return None
    _seed_builtins()
    d = coll.find_one({"name": (name or "").strip().lower()})
    return _public(d) if d else None


def set_scene_actions(name: str, actions: List[Dict[str, str]]) -> Dict[str, Any]:
    """Customise what a scene does to the room. Works for built-ins too."""
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
    """Return a scene's stored actions (data) for an app to execute.

    No hardware is actuated — the action list is returned as-is so a caller
    (e.g. iPhone Shortcuts) can run it. Re-applying any scene cancels timed
    reverts still pending from the previous one, then schedules this scene's
    own `for_min` reverts as data.
    """
    sc = get_scene(name)
    if not sc:
        return {"ok": False, "error": "not_found"}

    timers = 0
    tcoll = _timers()
    if tcoll is not None:
        # new scene supersedes this user's old reverts
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
    # **ونشغّلها فعلًا.**
    #
    # كانت بترجّع قائمة الأوامر كبيانات وبس، والتعليق فوق مكتوب فيه «ما في عتاد
    # بينشغّل». يعني «شغّلي مشهد الدراسة» بترد «تمام» وما بيصير ولا إشي —
    # وهاد أسوأ نوع فشل: بيبلّغ نجاحًا ما صار.
    #
    # القائمة ضلّت بترجع كمان، لأنّ في زبون (اختصارات الآيفون) بينفّذها بنفسه،
    # والأجهزة اللي مش عند هالمالك بتفشل بهدوء — كل أمر لحاله.
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
    """Send each action to its device. Returns (sent, names that do not exist).

    `missed` is returned rather than swallowed because a scene naming a device
    the owner does not own is a **setup** problem, not a runtime one — and the
    only way he ever finds out is if something says so. The built-in scenes ship
    with generic names (`light`, `fan`, `curtain`) that match a room node, so on
    a robot-only setup most of them will land here until he edits the scene.
    """
    from app.features.device_store import (
        command_payload, device_topic, get_device, set_state,
    )
    from app.integrations.room_device import get_room_device_client

    sent, missed = 0, []
    for a in actions or []:
        name = str(a.get("device") or "").strip().lower()
        value = str(a.get("value") or "").strip()
        if not name:
            continue
        try:
            device = get_device(name)
            if device is None:
                missed.append(name)
                continue
            # نفس بوّابة التحقّق اللي بتستعملها أداة الأجهزة — مش مسار تاني.
            # مسارين بيتحقّقوا من نفس الأمر بيفترقوا يوم ما، وساعتها بيصير في
            # طريق بيقبل قيمة الطريق التاني بيرفضها.
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
        except Exception as exc:  # noqa: BLE001 — one bad device is not a bad scene
            logger.debug("[SceneStore] %s failed: %s", name, exc)
            missed.append(name)
    return sent, missed


def run_due_timers() -> List[Dict[str, str]]:
    """Return any timed reverts whose moment has come. Call every minute.

    Returns the due revert actions as data (a list of {device, value}) and
    clears them from the store; a caller can hand them to an app to execute.
    A scheduler job — it runs inside the active user's profile context, so it
    only ever fires that user's own scene timers.
    """
    tcoll = _timers()
    if tcoll is None:
        return []
    due: List[Dict[str, str]] = []
    # سقف لكل دورة: المؤقتات المستحقة بتنمسح وقت ما بتنقرا، فاللي فوق السقف
    # بيوصل بالدورة الجاي بدل ما ينضاع.
    for t in list(tcoll.find({"fire_at": {"$lte": _now()}}).limit(MAX_DUE_TIMERS)):
        due.append({"device": t.get("device", ""), "value": t.get("value", "")})
        tcoll.delete_one({"_id": t["_id"]})
    return due
