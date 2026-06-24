"""اليوميات — ساندي بتدوّن أحداث يومك وبتفتش فيها لاحقاً.

Collection: sandy_journal
  {_id, date "YYYY-MM-DD", text, at (datetime UTC)}

كل تدوينة سطر مستقل (مش مستند واحد باليوم) — أسهل للبحث والعرض الزمني.
عزل المستأجرين مفروض من طبقة scoped(): _coll() ترجع None لو ما في مستأجر.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from app.utils.tenant_db import scoped
from app.utils.time import USER_TZ

_COLL = "sandy_journal"
_mongo_db = None


def init_journal_store(mongo_db) -> None:
    global _mongo_db
    _mongo_db = mongo_db
    if mongo_db is None:
        return
    try:
        mongo_db[_COLL].create_index([("user_id", 1), ("date", -1)], background=True)
        print("[JournalStore] ready")
    except Exception as e:  # noqa: BLE001
        print(f"[JournalStore] index skipped: {e}")


def _coll():
    """Tenant-scoped journal collection, or None when no db / no active tenant."""
    return scoped(_mongo_db, _COLL)


def add_entry(text: str, date: str = "") -> bool:
    coll = _coll()
    if coll is None:
        return False
    text = str(text or "").strip()
    if not text:
        return False
    coll.insert_one(
        {
            "_id": uuid.uuid4().hex,
            "date": (date or datetime.now(USER_TZ).date().isoformat())[:10],
            "text": text,
            "at": datetime.now(timezone.utc),
        }
    )
    return True


def entries_for(date: str = "", limit: int = 50) -> List[Dict[str, Any]]:
    """تدوينات يوم معيّن (افتراضياً اليوم)، الأقدم أولاً."""
    coll = _coll()
    if coll is None:
        return []
    d = (date or datetime.now(USER_TZ).date().isoformat())[:10]
    out = []
    for doc in coll.find({"date": d}).sort("at", 1).limit(limit):
        out.append({"id": doc["_id"], "date": doc["date"], "text": doc.get("text", "")})
    return out


def recent_entries(limit: int = 30) -> List[Dict[str, Any]]:
    """آخر التدوينات عبر الأيام، الأحدث أولاً."""
    coll = _coll()
    if coll is None:
        return []
    out = []
    for doc in coll.find({}).sort("at", -1).limit(limit):
        out.append({"id": doc["_id"], "date": doc["date"], "text": doc.get("text", "")})
    return out


def search_entries(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """بحث نصي بسيط (احتواء) — «إيمتى آخر مرة رحت عالطبيب؟»"""
    coll = _coll()
    if coll is None:
        return []
    ql = str(query or "").strip().lower()
    if not ql:
        return []
    out = []
    for doc in coll.find({}).sort("at", -1).limit(2000):
        if ql in (doc.get("text", "") or "").lower():
            out.append({"id": doc["_id"], "date": doc["date"], "text": doc.get("text", "")})
            if len(out) >= limit:
                break
    return out


def delete_entry(entry_id: str) -> bool:
    coll = _coll()
    if coll is None or not entry_id:
        return False
    return coll.delete_one({"_id": entry_id}).deleted_count > 0
