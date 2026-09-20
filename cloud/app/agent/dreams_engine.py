"""E1 — محرك الأحلام المشتركة (Shared Dreams Engine).

يفحص الأهداف النشطة (sandy_goals) ويبني تذكيراً بالأهداف اللي قرّب موعدها —
Sandy تذكر المستخدم بأحلامه ولا تتركها تُنسى.

الأهداف الراكدة مش هون: proactive_goals بيغطيها، والاثنين بينادوا بنفس دور
الدردشة — لما كان هون كمان، نفس الهدف كان ينحقن بالبرومبت مرتين بتوجيهين.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app.db import get_db
from app.utils.tenant_db import scoped

logger = logging.getLogger(__name__)

_COLL = "sandy_goals"
_DEADLINE_HORIZON = 7  # موعد خلال أسبوع → ذكّر بإلحاح


def get_dream_reminders(limit: int = 3) -> List[dict]:
    """يرجع أهداف نشطة موعدها خلال _DEADLINE_HORIZON يوم (أقربها أولاً)."""
    coll = scoped(get_db(), _COLL, field="chat_id")
    if coll is None:
        return []

    try:
        now = datetime.now(timezone.utc)
        deadline_cutoff = (now + timedelta(days=_DEADLINE_HORIZON)).date().isoformat()

        docs = list(coll.find(
            {"status": "active", "deadline": {"$lte": deadline_cutoff, "$ne": None}},
            {"_id": 0, "text": 1, "deadline": 1},
            sort=[("deadline", 1)],
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

    parts = [f"{d.get('text', '')[:60]} (موعد: {d['deadline']})" for d in reminders]
    return "[أهداف موعدها قرّب: " + " | ".join(parts) + "]"
