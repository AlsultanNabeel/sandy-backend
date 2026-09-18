"""E1 — محرك الأحلام المشتركة (Shared Dreams Engine).

يفحص الأهداف النشطة (sandy_goals) ويبني تذكيراً ذكياً عن الأهداف الراكدة
أو الأهداف التي اقترب موعدها — Sandy تذكر المستخدم بأحلامه ولا تتركها تُنسى.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app.db import get_db
from app.utils.tenant_db import scoped

logger = logging.getLogger(__name__)

_COLL = "sandy_goals"
_STALE_DAYS = 7        # هدف ما تغيّر له أسبوع → ذكّر
_DEADLINE_HORIZON = 7  # موعد خلال أسبوع → ذكّر بإلحاح


def get_dream_reminders(limit: int = 3) -> List[dict]:
    """يرجع قائمة بأهداف تستحق التذكير الآن."""
    coll = scoped(get_db(), _COLL, field="chat_id")
    if coll is None:
        return []

    try:
        now = datetime.now(timezone.utc)
        stale_cutoff = now - timedelta(days=_STALE_DAYS)
        deadline_cutoff = (now + timedelta(days=_DEADLINE_HORIZON)).date().isoformat()

        docs = list(coll.find(
            {
                "status": "active",
                "$or": [
                    {"updated_at": {"$lt": stale_cutoff}},
                    {"deadline": {"$lte": deadline_cutoff, "$ne": None}},
                ],
            },
            {"_id": 0, "text": 1, "deadline": 1, "updated_at": 1},
            sort=[("updated_at", 1)],
            limit=limit,
        ))
        return docs
    except Exception as exc:
        logger.warning("[dreams_engine] read failed: %s", exc)
        return []


def get_dreams_context() -> Optional[str]:
    """يبني سطر hint لـ soul_node."""
    reminders = get_dream_reminders(limit=2)
    if not reminders:
        return None

    parts: list[str] = []
    for d in reminders:
        text = d.get("text", "")[:60]
        deadline = d.get("deadline")
        if deadline:
            parts.append(f"{text} (موعد: {deadline})")
        else:
            parts.append(f"{text} (راكد)")

    return "[أهداف تحتاج اهتمام: " + " | ".join(parts) + "]"
