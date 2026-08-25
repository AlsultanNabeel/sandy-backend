"""A1 — الذاكرة العاطفية طويلة الأمد.

يحفظ اللحظات العاطفية المهمة في MongoDB ويسترجعها
لإثراء persona_snippet في soul_node.
"""

from __future__ import annotations
import logging

from datetime import datetime, timezone
from typing import Optional

from app.db import get_db
from app.utils.tenant_db import scoped

_COLL = "sandy_memories"
_LABEL = "emotional_memory"

_SIGNIFICANT_MOODS = {"stressed", "frustrated", "sad", "angry"}
_POSITIVE_MOODS = {"happy", "excited", "playful"}
_ALL_TRACKED = _SIGNIFICANT_MOODS | _POSITIVE_MOODS

def _coll():
    """The tenant-scoped handle, and the only way in here.

    These modules used to take `chat_id` and `mongo_db` as arguments and write
    on the raw collection with the tenant stamped by hand — the exact pattern
    `tenant_db` exists to abolish, and the one thing `ARCHITECTURE_MAP` §2.6
    says must never come back on a request path. It was invisible to
    `test_tenant_scoping_guard.py`, so one forgotten filter would have been a
    cross-tenant leak with nothing watching.

    They could not move before: they run on background threads, and the tenant
    lives in a `ContextVar` that did not cross one. `submit_background` carries
    it now (§2.5), so the scoping works where it is actually called.
    """
    return scoped(get_db(), _COLL, field="chat_id")


_MOOD_AR = {
    "stressed": "متوتر",
    "frustrated": "محبط",
    "sad": "حزين",
    "angry": "غاضب",
    "happy": "سعيد",
    "excited": "متحمس",
    "playful": "مرح",
}


def save_emotional_moment(mood: str, topic: str) -> None:
    """احفظ لحظة عاطفية مهمة في LTM.

    يُستدعى من graph.py بعد response_node عند mood مهم.
    """
    coll = _coll()
    if coll is None or mood not in _ALL_TRACKED:
        return
    try:
        from app.agent.ltm_crypto import encrypt_field
        from app.utils.user_profiles import current_user_id
        coll.insert_one({
            "user_id": str(current_user_id() or ""),
            "label": _LABEL,
            "mood": mood,
            "topic": encrypt_field(str(topic)[:200]),
            "created_at": datetime.now(timezone.utc),
        })
    except Exception:
        logging.getLogger(__name__).debug("ignoring non-critical error", exc_info=True)


def get_emotional_context(limit: int = 3) -> Optional[str]:
    """اجلب آخر لحظات عاطفية كـ context موجز لـ soul_node.

    يُرجع None إذا لا يوجد تاريخ عاطفي أو قاعدة البيانات غير متاحة.
    """
    coll = _coll()
    if coll is None:
        return None
    try:
        docs = list(coll.find(
            {"label": _LABEL},
            {"_id": 0, "mood": 1, "topic": 1, "created_at": 1},
            sort=[("created_at", -1)],
            limit=limit,
        ))
    except Exception:
        return None

    if not docs:
        return None

    from app.agent.ltm_crypto import decrypt_field
    parts = []
    for d in docs:
        raw_date = d.get("created_at")
        date_str = raw_date.strftime("%m/%d") if hasattr(raw_date, "strftime") else ""
        mood_ar = _MOOD_AR.get(d.get("mood", ""), d.get("mood", ""))
        topic = decrypt_field(d.get("topic", ""))
        parts.append(f"{date_str} {mood_ar}: {topic}" if date_str else f"{mood_ar}: {topic}")

    return "[ذاكرة: " + " | ".join(parts) + "]"
