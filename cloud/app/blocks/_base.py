"""What the three block stores share: the scoped handle, filters, output shape."""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.db import get_db
from app.utils.tenant_db import scoped

ENTRIES = "sandy_entries"
ITEMS = "sandy_items"
SCHEDULES = "sandy_schedules"

MAX_LIMIT = 500


def coll(name: str, mongo_db=None):
    """Tenant-scoped handle, or None with no db or no tenant (fail closed)."""
    return scoped(mongo_db if mongo_db is not None else get_db(), name)


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(timezone.utc)


def migrated_ref(ref: Optional[Dict[str, Any]]) -> Optional[Dict[str, str]]:
    if not ref:
        return None
    return {"collection": str(ref["collection"]), "id": str(ref["id"])}


def text_filter(text: str) -> Dict[str, Any]:
    return {"text": {"$regex": re.escape(text), "$options": "i"}}


def range_filter(since: Optional[datetime], until: Optional[datetime]) -> Optional[Dict[str, Any]]:
    """``{"$gte": since, "$lt": until}`` with the missing ends left out."""
    rng: Dict[str, Any] = {}
    if since is not None:
        rng["$gte"] = since
    if until is not None:
        rng["$lt"] = until
    return rng or None


def clamp(limit: int) -> int:
    return max(1, min(int(limit or MAX_LIMIT), MAX_LIMIT))


def out(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Public shape: ``id`` instead of ``_id``; tenant and vector left out."""
    if doc is None:
        return None
    shaped = {k: v for k, v in doc.items() if k not in ("_id", "user_id", "embedding")}
    shaped["id"] = doc["_id"]
    return shaped
