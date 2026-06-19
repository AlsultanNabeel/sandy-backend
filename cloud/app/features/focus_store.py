"""وضع التركيز — مؤقت دراسة/شغل (بومودورو).

Collection: sandy_focus
  {_id, label, minutes, started_at, ends_at, state: active|done|cancelled,
   reminder_id}

التنبيه عند النهاية بمر عبر نظام التذكيرات نفسه (مخزَّن في Mongo) — يعني
بنجو من إعادة تشغيل السيرفر، وبوصل تيليجرام بأزرار الغفوة العادية.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.utils.time import USER_TZ
from app.utils.user_profiles import active_profile_allows_privileged_access

_COLL = "sandy_focus"
_META = "sandy_focus_meta"   # {_id: "sounds", start, break, end}  أصوات قابلة للتغيير
_mongo_db = None

# الأصوات الافتراضية لكل حدث — مخزّنة كبيانات فقط (تستهلكها الواجهة/التطبيق).
_DEFAULT_SOUNDS = {"start": "focus_start", "break": "focus_break", "end": "focus_end"}


def init_focus_store(mongo_db) -> None:
    global _mongo_db
    _mongo_db = mongo_db
    if mongo_db is not None:
        print("[FocusStore] ready")


def _require_owner() -> None:
    if not active_profile_allows_privileged_access():
        raise PermissionError("هذا خاص بنبيل 😊")


def get_focus_sounds() -> Dict[str, str]:
    """صوت البازر المضبوط لكل حدث (start/break/end) فوق الافتراضي."""
    out = dict(_DEFAULT_SOUNDS)
    if _mongo_db is not None:
        doc = _mongo_db[_META].find_one({"_id": "sounds"}) or {}
        for k in out:
            if doc.get(k):
                out[k] = doc[k]
    return out


def set_focus_sound(event: str, melody: str) -> Dict[str, Any]:
    """غيّر صوت حدث (start|break|end) — مخزّن كبيانات تستهلكها الواجهة/التطبيق."""
    _require_owner()
    event = (event or "").strip().lower()
    melody = (melody or "").strip().lower()
    if event not in _DEFAULT_SOUNDS:
        return {"ok": False, "error": "bad_event"}
    if not melody:
        return {"ok": False, "error": "bad_melody"}
    if _mongo_db is None:
        return {"ok": False}
    _mongo_db[_META].update_one({"_id": "sounds"}, {"$set": {event: melody}}, upsert=True)
    return {"ok": True, "event": event, "melody": melody}


def _phase_total_sec(s: Dict[str, Any]) -> int:
    """Total length of the current phase in seconds (for the countdown ring)."""
    if s.get("phase", "focus") == "break":
        return int(s.get("break_min", 0)) * 60
    return int(s.get("focus_min", s.get("minutes", 0))) * 60


def active_focus() -> Optional[Dict[str, Any]]:
    if _mongo_db is None:
        return None
    return _mongo_db[_COLL].find_one({"state": "active"})


def start_focus(focus_min: int = 25, label: str = "", break_min: int = 0,
                cycles: int = 1, scene: str = "", end_scene: str = "") -> Dict[str, Any]:
    """يبدأ جلسة تركيز/بومودورو ويشغّل مشهد الغرفة المربوط فيها.

    focus_min/break_min/cycles كلها يحددها المالك. `scene` بيتطبّق عند البداية.
    `end_scene` (اختياري) بيتطبّق لما تخلص الجلسة كلها — وبدونه الغرفة بتضل
    على حالها فما يطفّي إشي وإنت لسا موجود. انتقالات الأطوار بتمر عبر
    advance_focus_phase() اللي بتنده الجدولة كل دقيقة.
    """
    _require_owner()
    if _mongo_db is None:
        return {"ok": False}
    if active_focus():
        return {"ok": False, "error": "already_active"}
    focus_min = max(1, min(240, int(focus_min or 25)))
    break_min = max(0, min(120, int(break_min or 0)))
    cycles = max(1, min(12, int(cycles or 1)))
    now = datetime.now(timezone.utc)

    scene_result = None
    if scene:
        try:
            from app.features.scene_store import apply_scene
            scene_result = apply_scene(scene)
        except Exception as e:  # noqa: BLE001
            print(f"[FocusStore] scene apply failed: {e}")

    doc = {
        "_id": uuid.uuid4().hex,
        "label": str(label or "").strip(),
        "scene": str(scene or "").strip().lower(),
        "end_scene": str(end_scene or "").strip().lower(),
        "focus_min": focus_min,
        "break_min": break_min,
        "cycles": cycles,
        "cycle_idx": 1,
        "phase": "focus",
        "phase_ends_at": now + timedelta(minutes=focus_min),
        "started_at": now,
        "state": "active",
    }
    _mongo_db[_COLL].insert_one(doc)
    return {
        "ok": True, "focus_min": focus_min, "break_min": break_min,
        "cycles": cycles, "label": label, "scene": scene,
        # Stored action list of the applied scene (data for an app to execute).
        "scene_actions": (scene_result or {}).get("actions", []),
    }


def _aware(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def stop_focus(completed: bool = True) -> Dict[str, Any]:
    """ينهي الجلسة. completed=True إنجاز (احتفال)، False = إلغاء.
    لو الجلسة مربوط فيها end_scene بيتطبّق عند الإنجاز."""
    _require_owner()
    s = active_focus()
    if not s:
        return {"ok": False, "error": "no_session"}

    now = datetime.now(timezone.utc)
    started = _aware(s["started_at"])
    elapsed_min = max(0, int((now - started).total_seconds() / 60))

    # Focused minutes actually earned — what the stats and goals count. Full
    # completion = all focus cycles; a cancel counts the cycles finished plus
    # however far into the current focus phase we got (breaks don't count).
    focus_min = int(s.get("focus_min", 0))
    cycle_idx = int(s.get("cycle_idx", 1))
    if completed:
        focused_min = focus_min * int(s.get("cycles", 1))
    else:
        focused_min = focus_min * (cycle_idx - 1)
        if s.get("phase", "focus") == "focus":
            pe = _aware(s.get("phase_ends_at"))
            rem = max(0, (pe - now).total_seconds()) if pe else 0
            focused_min += max(0, int((focus_min * 60 - rem) // 60))
    focused_min = max(0, focused_min)

    _mongo_db[_COLL].update_one(
        {"_id": s["_id"]},
        {"$set": {"state": "done" if completed else "cancelled",
                  "ended_at": now, "focused_min": focused_min}},
    )
    if completed and s.get("end_scene"):
        try:
            from app.features.scene_store import apply_scene
            apply_scene(s["end_scene"])
        except Exception:
            pass

    return {
        "ok": True,
        "minutes": elapsed_min,
        "planned": s.get("focus_min", s.get("minutes", 0)),
        "label": s.get("label", ""),
        "completed": completed,
    }


def advance_focus_phase() -> Optional[Dict[str, Any]]:
    """تنقل جلسة البومودورو لطورها التالي لو خلص وقت الطور الحالي.

    بترجع حدث {event: focus|break|done, ...} للجدولة تبعت إشعاره، أو None لو ما
    في شي مستحق. عند الرجوع للتركيز بتعيد تطبيق المشهد (لأن الراحة أو مؤقت
    داخل المشهد ممكن يكون غيّر الغرفة).
    """
    if _mongo_db is None:
        return None
    s = active_focus()
    if not s or s.get("state") != "active":
        return None
    pe = _aware(s.get("phase_ends_at"))
    now = datetime.now(timezone.utc)
    if pe is None or now < pe:
        return None

    phase = s.get("phase", "focus")
    cycle_idx = int(s.get("cycle_idx", 1))
    cycles = int(s.get("cycles", 1))
    focus_min = int(s.get("focus_min", 25))
    break_min = int(s.get("break_min", 0))
    label = s.get("label", "")

    # خلص آخر طور تركيز → إنهاء الجلسة كلها
    if phase == "focus" and cycle_idx >= cycles:
        r = stop_focus(completed=True)
        return {"event": "done", "label": label, "cycles": cycles,
                "minutes": r.get("minutes", 0)}

    # خلص تركيز وفي راحة → ادخل طور الراحة
    if phase == "focus" and break_min > 0:
        _mongo_db[_COLL].update_one(
            {"_id": s["_id"]},
            {"$set": {"phase": "break", "phase_ends_at": now + timedelta(minutes=break_min)}},
        )
        return {"event": "break", "break_min": break_min,
                "cycle_idx": cycle_idx, "cycles": cycles, "label": label}

    # خلصت راحة (أو تركيز بدون راحة) → دورة تركيز جديدة
    cycle_idx += 1
    _mongo_db[_COLL].update_one(
        {"_id": s["_id"]},
        {"$set": {"phase": "focus", "cycle_idx": cycle_idx,
                  "phase_ends_at": now + timedelta(minutes=focus_min)}},
    )
    if s.get("scene"):
        try:
            from app.features.scene_store import apply_scene
            apply_scene(s["scene"])
        except Exception:
            pass
    return {"event": "focus", "cycle_idx": cycle_idx, "cycles": cycles,
            "focus_min": focus_min, "label": label}


def focus_status() -> Dict[str, Any]:
    _require_owner()
    s = active_focus()
    if not s:
        return {"active": False}
    pe = _aware(s.get("phase_ends_at"))
    now = datetime.now(timezone.utc)
    remaining_sec = max(0, int((pe - now).total_seconds())) if pe else 0
    return {
        "active": True,
        "label": s.get("label", ""),
        "scene": s.get("scene", ""),
        "phase": s.get("phase", "focus"),
        "cycle_idx": int(s.get("cycle_idx", 1)),
        "cycles": int(s.get("cycles", 1)),
        "focus_min": int(s.get("focus_min", s.get("minutes", 0))),
        "break_min": int(s.get("break_min", 0)),
        "remaining_min": remaining_sec // 60,
        # seconds-precise fields for the live countdown ring (web/app):
        "remaining_sec": remaining_sec,
        "total_sec": _phase_total_sec(s),
        "phase_ends_at_ms": int(pe.timestamp() * 1000) if pe else 0,
    }


# ── History, stats & goals ──────────────────────────────────────────────────

_GOAL_KEYS = ("day", "week", "month", "year")


def focus_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Finished sessions, newest first — the review list."""
    _require_owner()
    if _mongo_db is None:
        return []
    limit = max(1, min(200, int(limit or 50)))
    out: List[Dict[str, Any]] = []
    cur = (_mongo_db[_COLL]
           .find({"state": {"$in": ["done", "cancelled"]}})
           .sort("started_at", -1).limit(limit))
    for d in cur:
        started = _aware(d.get("started_at"))
        ended = _aware(d.get("ended_at"))
        minutes = d.get("focused_min")
        if minutes is None and started and ended:
            minutes = int((ended - started).total_seconds() / 60)
        out.append({
            "id": d.get("_id"),
            "label": d.get("label", ""),
            "scene": d.get("scene", ""),
            "completed": d.get("state") == "done",
            "minutes": max(0, int(minutes or 0)),
            "cycles": int(d.get("cycles", 1)),
            "started_at": started.astimezone(USER_TZ).isoformat() if started else None,
            "ended_at": ended.astimezone(USER_TZ).isoformat() if ended else None,
        })
    return out


def get_focus_goals() -> Dict[str, int]:
    """Target focused-minutes per period (0 = no goal set)."""
    out = {k: 0 for k in _GOAL_KEYS}
    if _mongo_db is None:
        return out
    doc = _mongo_db[_META].find_one({"_id": "goals"}) or {}
    for k in _GOAL_KEYS:
        try:
            out[k] = max(0, int(doc.get(k, 0) or 0))
        except (TypeError, ValueError):
            out[k] = 0
    return out


def set_focus_goal(period: str, minutes: int) -> Dict[str, Any]:
    """Set a daily/weekly/monthly/yearly focus target (in minutes)."""
    _require_owner()
    period = (period or "").strip().lower()
    if period not in _GOAL_KEYS:
        return {"ok": False, "error": "bad_period", "choices": list(_GOAL_KEYS)}
    if _mongo_db is None:
        return {"ok": False}
    try:
        minutes = max(0, min(100000, int(minutes)))
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad_minutes"}
    _mongo_db[_META].update_one({"_id": "goals"}, {"$set": {period: minutes}}, upsert=True)
    return {"ok": True, "period": period, "minutes": minutes}


def _period_starts() -> Dict[str, datetime]:
    """UTC datetimes for the start of today/week/month/year in the user's tz.
    The week starts on Saturday (local convention)."""
    local = datetime.now(timezone.utc).astimezone(USER_TZ)
    today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    week = today - timedelta(days=(local.weekday() - 5) % 7)
    return {
        "day": today.astimezone(timezone.utc),
        "week": week.astimezone(timezone.utc),
        "month": today.replace(day=1).astimezone(timezone.utc),
        "year": today.replace(month=1, day=1).astimezone(timezone.utc),
    }


def focus_stats() -> Dict[str, Any]:
    """Focused-minute totals + session counts + goal progress per period."""
    _require_owner()
    empty = {k: {"minutes": 0, "sessions": 0, "goal_min": 0, "pct": 0} for k in _GOAL_KEYS}
    if _mongo_db is None:
        return empty
    goals = get_focus_goals()
    out: Dict[str, Any] = {}
    for key, start in _period_starts().items():
        agg = list(_mongo_db[_COLL].aggregate([
            {"$match": {"state": {"$in": ["done", "cancelled"]},
                        "ended_at": {"$gte": start}}},
            {"$group": {"_id": None,
                        "minutes": {"$sum": {"$ifNull": ["$focused_min", 0]}},
                        "sessions": {"$sum": 1}}},
        ]))
        minutes = int(agg[0]["minutes"]) if agg else 0
        target = int(goals.get(key, 0))
        out[key] = {
            "minutes": minutes,
            "sessions": int(agg[0]["sessions"]) if agg else 0,
            "goal_min": target,
            "pct": min(100, int(minutes * 100 / target)) if target else 0,
        }
    return out
