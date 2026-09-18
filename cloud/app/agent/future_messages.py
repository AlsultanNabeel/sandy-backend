"""E3 — الرسائل المجدولة للمستقبل (Future Messages).

المستخدم يطلب: "ذكريني بعد شهر إني كنت قلت كذا" أو "اكتبيلي رسالة لنفسي بعد سنة"
نحفظ الرسالة + تاريخ التسليم. عند أول رسالة بعد التاريخ → تُسلَّم Sandy للمستخدم.

التسليم: passive — Sandy تذكرها في الرد التالي بعد تاريخ التسليم.

Storage goes through the tenant-scoped handle (``chat_id`` is the tenant
field), like every other per-user store. The module used to take ``chat_id``
and ``mongo_db`` and filter the raw collection by hand, and the agent tool fed
it ``state["chat_id"]`` with a ``"default"`` fallback, so an unauthenticated
turn could write into a shared bucket. The tenant now comes only from
``current_user_id()``; with no tenant every call is a no-op.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.db import get_db
from app.utils.tenant_db import scoped

logger = logging.getLogger(__name__)

_COLL = "sandy_future_messages"
_MAX_TEXT_CHARS = 500


def _coll():
    return scoped(get_db(), _COLL, field="chat_id")


def schedule_future_message(text: str, deliver_at: datetime) -> bool:
    """احفظ رسالة لتسلَّم في وقت لاحق."""
    coll = _coll()
    if coll is None or not (text or "").strip():
        return False
    try:
        from app.agent.ltm_crypto import encrypt_field
        from app.utils.user_profiles import current_user_id

        deliver_utc = (
            deliver_at.astimezone(timezone.utc)
            if deliver_at.tzinfo
            else deliver_at.replace(tzinfo=timezone.utc)
        )
        coll.insert_one({
            "user_id": str(current_user_id() or ""),
            "text": encrypt_field(text.strip()[:_MAX_TEXT_CHARS]),
            "deliver_at": deliver_utc,
            "delivered": False,
            "created_at": datetime.now(timezone.utc),
        })
        logger.info("[future_messages] scheduled for %s", deliver_utc.isoformat())
        return True
    except Exception as exc:
        logger.warning("[future_messages] schedule failed: %s", exc)
        return False


def list_pending_messages(limit: int = 200) -> List[Dict[str, Any]]:
    """Undelivered messages for the current tenant, soonest first (raw docs)."""
    coll = _coll()
    if coll is None:
        return []
    try:
        return list(
            coll.find(
                {"delivered": {"$ne": True}},
                {"text": 1, "deliver_at": 1, "created_at": 1},
            ).sort("deliver_at", 1).limit(limit)
        )
    except Exception as exc:
        logger.warning("[future_messages] list failed: %s", exc)
        return []


def cancel_message(msg_id: Any) -> bool:
    """Delete one still-undelivered message of the current tenant."""
    coll = _coll()
    if coll is None:
        return False
    try:
        res = coll.delete_one({"_id": msg_id, "delivered": {"$ne": True}})
        return res.deleted_count > 0
    except Exception as exc:
        logger.warning("[future_messages] cancel failed: %s", exc)
        return False


def pop_due_messages(limit: int = 3) -> List[dict]:
    """يجلب الرسائل المستحقة الآن ويعلّمها delivered=True (atomic per message).

    يُستدعى مرة عند كل رسالة من المستخدم — passive delivery.
    """
    coll = _coll()
    if coll is None:
        return []
    try:
        now = datetime.now(timezone.utc)
        delivered = []
        for _ in range(limit):
            doc = coll.find_one_and_update(
                {"delivered": False, "deliver_at": {"$lte": now}},
                {"$set": {"delivered": True, "delivered_at": now}},
                projection={"_id": 0, "text": 1, "deliver_at": 1, "created_at": 1},
                sort=[("deliver_at", 1)],
            )
            if not doc:
                break
            delivered.append(doc)
        return delivered
    except Exception as exc:
        logger.warning("[future_messages] pop failed: %s", exc)
        return []


def get_future_messages_context() -> Optional[str]:
    """إذا في رسائل مستحقة، يُسلَّمها كـ context لـ Sandy لتذكر المستخدم بها."""
    due = pop_due_messages()
    if not due:
        return None

    from app.agent.ltm_crypto import decrypt_field
    parts = []
    for d in due:
        created = d.get("created_at")
        created_str = created.strftime("%Y/%m/%d") if hasattr(created, "strftime") else ""
        msg = decrypt_field(d.get("text", ""))[:200]
        parts.append(f"({created_str}): {msg}" if created_str else msg)

    return "[رسالة مجدولة من المستخدم لنفسه: " + " | ".join(parts) + "]"
