"""D2 — الدروس المستفادة (Lessons Learned LTM).

Sandy تكتشف عبارات "تعلمت كذا" / "اكتشفت إن" وتحفظها كدروس في sandy_memories،
ثم تذكر المستخدم بها عند الحاجة (proactive_context).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

from app.db import get_db
from app.utils.tenant_db import scoped
from app.utils.user_profiles import current_user_id

logger = logging.getLogger(__name__)


_COLL = "sandy_memories"
_LABEL = "lesson_learned"


def _coll():
    """The tenant-scoped handle, and the only way into storage here.

    This module used to take `chat_id` and `mongo_db` and write on the raw
    collection with the tenant stamped by hand — the pattern `tenant_db` exists
    to abolish, and the one `ARCHITECTURE_MAP` §2.6 says must never come back on
    a request path. It was invisible to `test_tenant_scoping_guard.py`, so a
    forgotten filter would have been a cross-tenant leak with nothing watching.

    It could not move before: these writers run on background threads and the
    tenant lives in a `ContextVar` that did not cross one. `submit_background`
    carries it now (§2.5), so the scoping works where it is actually called.
    """
    return scoped(get_db(), _COLL, field="chat_id")



# مؤشرات الدروس — العبارة + ما بعدها هو الدرس
_LESSON_SIGNALS = [
    "تعلمت إن", "تعلمت ان", "تعلمت اليوم", "اكتشفت إن", "اكتشفت ان",
    "فهمت إن", "فهمت ان", "الدرس إن", "الدرس ان",
    "صار في بالي", "استفدت إن", "استفدت ان",
    "i learned", "lesson learned",
]

_LESSON_RE = re.compile(
    r"(?:" + "|".join(re.escape(s) for s in _LESSON_SIGNALS) + r")\s+(.{8,200})",
    re.IGNORECASE,
)


def detect_lesson(message: str) -> Optional[str]:
    """يستخرج نص الدرس بعد العبارة المؤشرة."""
    if not message:
        return None
    m = _LESSON_RE.search(message)
    if not m:
        return None
    text = m.group(1).strip().rstrip(".،؛!? ")
    return text[:200] if len(text) >= 8 else None


def save_lesson(
    lesson: str,
) -> bool:
    """احفظ درساً جديداً."""
    coll = _coll()
    if coll is None or not lesson.strip():
        return False
    try:
        from app.agent.ltm_crypto import encrypt_field
        coll.insert_one({
            "user_id": str(current_user_id() or ""),
            "label": _LABEL,
            "lesson": encrypt_field(lesson.strip()[:200]),
            "created_at": datetime.now(timezone.utc),
        })
        logger.info(f"[lessons] saved: {lesson[:50]}")
        return True
    except Exception as exc:
        logger.debug(f"[lessons] save failed: {exc}")
        return False


def get_lessons_context(
    limit: int = 3,
) -> Optional[str]:
    """يرجع آخر دروس كـ context لـ soul_node — للتذكير."""
    coll = _coll()
    if coll is None:
        return None
    try:
        docs = list(coll.find(
            {"label": _LABEL},
            {"_id": 0, "lesson": 1},
            sort=[("created_at", -1)],
            limit=limit,
        ))
    except Exception:
        return None

    if not docs:
        return None

    from app.agent.ltm_crypto import decrypt_field
    lessons = [decrypt_field(d["lesson"]) for d in docs if d.get("lesson")]
    return "[دروس سابقة: " + " | ".join(lessons) + "]" if lessons else None


def save_detected_lesson(
    message: str,
) -> bool:
    """شامل: يكتشف ويحفظ. يُستدعى من graph.py في background."""
    lesson = detect_lesson(message)
    if not lesson:
        return False
    return save_lesson(lesson)
