"""تاريخ مشترك: يحفظ المعالم المهمة مع تواريخها.

بنخزّن الإنجازات والأحداث والذكريات مع تاريخها، وبنرجّع تذكير لما يرجع
نفس التاريخ في سنة لاحقة. نمط الحفظ بـ label="milestone" و event_date.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timezone
from typing import List, Optional, Tuple

from app.db import get_db
from app.utils.tenant_db import scoped
from app.utils.user_profiles import current_user_id

logger = logging.getLogger(__name__)


_COLL = "sandy_memories"
_LABEL = "milestone"


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



# كلمات بتدل على معلم مهم
_MILESTONE_SIGNALS = (
    "تخرجت", "تجوزت", "خطبت", "انتقلت", "استقلت", "تعينت",
    "وقّعت العقد", "بدأت شغل", "بدأت دراسة", "تركت", "بعت",
    "اشتريت بيت", "اشتريت سيارة", "خلصت", "تخرجنا",
    "نجحت", "ربحت", "أنجبت", "ولدت",
    "ذكرى", "مرت سنة", "مرت شهور",
)

_MILESTONE_RE = re.compile(
    r"(" + "|".join(re.escape(s) for s in _MILESTONE_SIGNALS) + r")"
    r"\s+(.{3,150})"
)


def detect_milestone(message: str) -> Optional[Tuple[str, str]]:
    """يرجّع (signal, context) لو في معلم مهم بالرسالة."""
    if not message:
        return None
    m = _MILESTONE_RE.search(message)
    if not m:
        return None
    signal = m.group(1)
    context = m.group(2).strip().rstrip(".،؛!? ")[:150]
    if len(context) < 3:
        return None
    return signal, context


def save_milestone(
    signal: str,
    context: str,
    event_date: Optional[date] = None,
) -> bool:
    """يحفظ معلم مع تاريخه."""
    coll = _coll()
    if coll is None or not signal:
        return False
    try:
        from app.agent.ltm_crypto import encrypt_field
        now_utc = datetime.now(timezone.utc)
        coll.insert_one({
            "user_id": str(current_user_id() or ""),
            "label": _LABEL,
            "signal": signal,
            "context": encrypt_field(context.strip()[:200]),
            "event_date": (event_date or now_utc.date()).isoformat(),
            "created_at": now_utc,
        })
        logger.info(f"[shared_history] milestone saved: {signal} {context[:40]}")
        return True
    except Exception as exc:
        logger.debug(f"[shared_history] save failed: {exc}")
        return False


def get_anniversaries(
    today: Optional[date] = None,
) -> List[dict]:
    """يرجّع ذكريات اليوم: نفس الشهر واليوم بس من سنين سابقة."""
    coll = _coll()
    if coll is None:
        return []
    try:
        today = today or date.today()
        target_mm_dd = today.strftime("-%m-%d")  # "-05-16"
        docs = list(coll.find(
            {
                    "label": _LABEL,
                "event_date": {"$regex": f"{target_mm_dd}$"},
            },
            {"_id": 0, "signal": 1, "context": 1, "event_date": 1},
            limit=5,
        ))
        # شيل ذكريات نفس السنة الحالية
        today_iso = today.isoformat()
        return [d for d in docs if d.get("event_date") != today_iso]
    except Exception as exc:
        logger.debug(f"[shared_history] anniversary check failed: {exc}")
        return []


def get_anniversary_context(
) -> Optional[str]:
    """يرجّع سطر ذكرى للرسائل الاستباقية، أو None لو ما في."""
    anniv = get_anniversaries()
    if not anniv:
        return None
    first = anniv[0]
    try:
        from app.agent.ltm_crypto import decrypt_field
        year = first["event_date"][:4]
        years_ago = date.today().year - int(year)
        if years_ago <= 0:
            return None
        context = decrypt_field(first.get("context", ""))[:80]
        return f"[ذكرى مرت {years_ago} سنة: {first.get('signal')} {context}]"
    except Exception:
        return None


def save_detected_milestone(
    message: str,
) -> bool:
    """يكتشف ويحفظ بخطوة وحدة. بيستدعيه graph.py بالخلفية."""
    detected = detect_milestone(message)
    if not detected:
        return False
    signal, context = detected
    return save_milestone(signal, context)
