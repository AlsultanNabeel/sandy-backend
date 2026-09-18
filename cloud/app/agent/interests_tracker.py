"""C2 — متتبّع الاهتمامات (Interests Tracker).

يستخرج اهتمامات المستخدم من رسائله ويحفظها كـ keyword frequency في sandy_memories.
يُستخدم لمشاركة محتوى ذكي (``get_top_interests`` → share_api و content_share_tools).

التحقيق ذو مرحلتين:
  1. detect_interest_keywords() — regex على الرسالة، يستخرج keywords مرشحة
  2. bump_interest() — يزيد عداد كل keyword في mongo (sandy_memories label='interest')
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import List

from app.db import get_db
from app.utils.tenant_db import scoped
from app.utils.user_profiles import current_user_id

logger = logging.getLogger(__name__)


_COLL = "sandy_memories"
_LABEL = "interest"


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
    # `bump=False`: this counter is written on **every message** that mentions
    # anything, and the persona block that gets cached is built from the
    # `style_memory` / `preferences` / `relationship` / `lesson_learned` /
    # `conversation_summary` labels — never from `interest`. Left bumping, it
    # invalidated that cache once per turn and the cache never once hit.
    return scoped(get_db(), _COLL, field="chat_id", bump=False)


# مؤشرات الاهتمام — "بحب X" / "مهتم بـ X" / "حابب X" / "متابع X"
_INTEREST_RE = re.compile(
    r"(?:بحب|أحب|احب|مهتم\s+بـ?|حابب|متابع|بدرس|بتابع)\s+(?:ال)?([ء-ي]{3,30}(?:\s+[ء-ي]{3,15})?)",
)

# stopwords — مش اهتمامات حقيقية
_STOPWORDS = {
    "الموضوع", "الكلام", "الحكي", "الفكرة", "اشي", "شي", "الشي",
    "هاي", "هاد", "كذا", "هيك", "وقت", "اشياء",
}


def detect_interest_keywords(message: str) -> List[str]:
    """يستخرج كلمات-اهتمام مرشحة من الرسالة."""
    if not message:
        return []

    found = []
    for m in _INTEREST_RE.finditer(message):
        kw = m.group(1).strip()
        if kw in _STOPWORDS or len(kw) < 3:
            continue
        found.append(kw)
    return found


def bump_interest(
    keyword: str,
) -> bool:
    """يزيد عداد keyword في sandy_memories. idempotent."""
    coll = _coll()
    if coll is None or not keyword.strip():
        return False
    try:
        now = datetime.now(timezone.utc)
        coll.update_one(
            {"label": _LABEL, "keyword": keyword.strip()},
            {
                "$inc": {"count": 1},
                "$set": {"user_id": str(current_user_id() or ""), "last_seen": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        return True
    except Exception as exc:
        logger.warning("[interests] bump failed: %s", exc)
        return False


def get_top_interests(
    limit: int = 5,
) -> List[str]:
    """يرجع أعلى اهتمامات المستخدم — مرتبة بالـ count."""
    coll = _coll()
    if coll is None:
        return []
    try:
        docs = list(coll.find(
            {"label": _LABEL},
            {"_id": 0, "keyword": 1, "count": 1},
            sort=[("count", -1)],
            limit=limit,
        ))
        return [d["keyword"] for d in docs if d.get("keyword")]
    except Exception:
        return []


def track_message_interests(
    message: str,
) -> int:
    """شامل: يكتشف ويزيد العدّاد. يُستدعى من graph.py في background."""
    keywords = detect_interest_keywords(message)
    bumped = 0
    for kw in keywords[:3]:  # حد أعلى لكل رسالة
        if bump_interest(kw):
            bumped += 1
    return bumped

