"""وضع التركيز (بومودورو) في sandy_focus؛ الأطوار بتتقدّم عند القراءة، بلا مؤقّت بالسيرفر."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.utils.tenant_db import scoped
from app.utils.time import USER_TZ
from app.db import configure, get_db

logger = logging.getLogger(__name__)

_COLL = "sandy_focus"

# The end scene (music, light) belongs to the moment the session ends. Nothing ends it on a
# timer, only the next read, so a session found over longer ago than this is closed without it:
# opening the app the next morning must not switch the room.
END_SCENE_LATE = timedelta(minutes=2)


def init_focus_store(mongo_db) -> None:
    configure(mongo_db)
    if mongo_db is not None:
        logger.info("[FocusStore] ready")


def _coll():
    return scoped(get_db(), _COLL)


def _phase_total_sec(s: Dict[str, Any]) -> int:
    if s.get("phase", "focus") == "break":
        return int(s.get("break_min", 0)) * 60
    return int(s.get("focus_min", s.get("minutes", 0))) * 60


def active_focus() -> Optional[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return None
    return coll.find_one({"state": "active"})


def start_focus(focus_min: int = 25, label: str = "", break_min: int = 0,
                cycles: int = 1, scene: str = "", end_scene: str = "") -> Dict[str, Any]:
    """يبدأ جلسة تركيز/بومودورو؛ `scene` عند البداية و`end_scene` (اختياري) عند الإنجاز."""
    coll = _coll()
    if coll is None:
        return {"ok": False}
    _catch_up()
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
            logger.warning(f"[FocusStore] scene apply failed: {e}")

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
    coll.insert_one(doc)
    return {
        "ok": True, "focus_min": focus_min, "break_min": break_min,
        "cycles": cycles, "label": label, "scene": scene,
        "scene_actions": (scene_result or {}).get("actions", []),
    }


def _aware(dt):
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def stop_focus(completed: bool = True, end_scene: bool = True) -> Dict[str, Any]:
    """ينهي الجلسة: completed=True إنجاز (وبيطبّق end_scene إلا لو end_scene=False)، False إلغاء."""
    coll = _coll()
    if coll is None:
        return {"ok": False, "error": "no_session"}
    s = active_focus()
    if not s:
        return {"ok": False, "error": "no_session"}

    now = datetime.now(timezone.utc)
    started = _aware(s["started_at"])
    elapsed_min = max(0, int((now - started).total_seconds() / 60))

    # Earned focus minutes: breaks don't count; a cancel counts finished cycles plus the partial one.
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

    coll.update_one(
        {"_id": s["_id"]},
        {"$set": {"state": "done" if completed else "cancelled",
                  "ended_at": now, "focused_min": focused_min}},
    )
    if completed and end_scene and s.get("end_scene"):
        try:
            from app.features.scene_store import apply_scene
            apply_scene(s["end_scene"])
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)

    return {
        "ok": True,
        "minutes": elapsed_min,
        "planned": s.get("focus_min", s.get("minutes", 0)),
        "label": s.get("label", ""),
        "completed": completed,
    }


def advance_focus_phase() -> Optional[Dict[str, Any]]:
    """ينقل الجلسة لطورها التالي لو خلص وقته؛ بيرجّع حدث {event: focus|break|done} أو None."""
    coll = _coll()
    if coll is None:
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

    if phase == "focus" and cycle_idx >= cycles:
        r = stop_focus(completed=True, end_scene=now - pe <= END_SCENE_LATE)
        return {"event": "done", "label": label, "cycles": cycles,
                "minutes": r.get("minutes", 0)}

    if phase == "focus" and break_min > 0:
        # From when the phase ended, not now, so a late catch-up keeps the real timeline.
        coll.update_one(
            {"_id": s["_id"]},
            {"$set": {"phase": "break", "phase_ends_at": pe + timedelta(minutes=break_min)}},
        )
        return {"event": "break", "break_min": break_min,
                "cycle_idx": cycle_idx, "cycles": cycles, "label": label}

    cycle_idx += 1
    new_end = pe + timedelta(minutes=focus_min)
    coll.update_one(
        {"_id": s["_id"]},
        {"$set": {"phase": "focus", "cycle_idx": cycle_idx,
                  "phase_ends_at": new_end}},
    )
    # Re-apply the scene only for a phase running now, not ones skipped while catching up.
    if s.get("scene") and new_end > now:
        try:
            from app.features.scene_store import apply_scene
            apply_scene(s["scene"])
        except Exception:
            logger.debug("ignoring non-critical error", exc_info=True)
    return {"event": "focus", "cycle_idx": cycle_idx, "cycles": cycles,
            "focus_min": focus_min, "label": label}


def _catch_up() -> None:
    """Advance through every phase that already ended (nothing does it on a timer)."""
    for _ in range(64):  # 12 cycles × 2 phases, with room to spare
        if advance_focus_phase() is None:
            return


def focus_status() -> Dict[str, Any]:
    _catch_up()
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
        "remaining_sec": remaining_sec,
        "total_sec": _phase_total_sec(s),
        "phase_ends_at_ms": int(pe.timestamp() * 1000) if pe else 0,
    }


# ── History ─────────────────────────────────────────────────────────────────


def focus_history(limit: int = 50) -> List[Dict[str, Any]]:
    """Finished sessions, newest first."""
    coll = _coll()
    if coll is None:
        return []
    limit = max(1, min(200, int(limit or 50)))
    out: List[Dict[str, Any]] = []
    cur = (coll
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
