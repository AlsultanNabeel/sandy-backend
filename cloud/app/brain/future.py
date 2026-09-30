"""Messages to your future self, delivered into the next chat reply.

Due `message_to_future_self` schedules go into the next chat turn's prompt, and
are marked "sent" only once a real reply exists, so a failed turn delivers
nothing. The mark matches on status "pending", so a row is marked once.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple

from app.utils.ltm_crypto import decrypt_field
from app.blocks import _base, schedules

KIND = "message_to_future_self"
MAX_DUE = 3
MAX_CHARS = 200


def _line(row: dict) -> str:
    text = row.get("text", "")
    if (row.get("payload") or {}).get("encrypted"):
        text = decrypt_field(text)
    created = row.get("created_at")
    day = created.strftime("%Y/%m/%d") if hasattr(created, "strftime") else ""
    return f"({day}): {text[:MAX_CHARS]}" if day else text[:MAX_CHARS]


def due_context(now: Optional[datetime] = None) -> Optional[Tuple[str, List[Any]]]:
    """(prompt line, ids) for the due messages, None when nothing is due."""
    now = now or datetime.now(timezone.utc)
    rows = schedules.list_schedules(KIND, status="pending", until=now, limit=MAX_DUE)
    if not rows:
        return None
    text = "[رسالة مجدولة من المستخدم لنفسه: " + " | ".join(_line(r) for r in rows) + "]"
    return text, [r["id"] for r in rows]


def mark_delivered(ids: List[Any]) -> int:
    coll = _base.coll(_base.SCHEDULES)
    if coll is None or not ids:
        return 0
    now = datetime.now(timezone.utc)
    res = coll.update_many({"_id": {"$in": list(ids)}, "kind": KIND, "status": "pending"},
                           {"$set": {"status": "sent", "fired_at": now,
                                     "payload.delivered_at": now}})
    return res.modified_count
