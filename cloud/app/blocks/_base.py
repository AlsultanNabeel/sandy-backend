"""What the three block stores share: the scoped handle, filters, output shape."""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

from app.db import get_db
from app.utils.tenant_db import scoped

ENTRIES = "sandy_entries"
ITEMS = "sandy_items"
SCHEDULES = "sandy_schedules"

MAX_LIMIT = 500


def coll(name: str, mongo_db=None):
    """Tenant-scoped handle, or None with no db or no tenant (fail closed)."""
    return scoped(mongo_db if mongo_db is not None else get_db(), name)


# ── the turn's journal ───────────────────────────────────────────────────────
# While a chat turn runs, every block write is noted with what was there before, so
# a regenerated or edited turn can take back what the first one did (`undo`).

_journal: ContextVar[Optional[List[Dict[str, Any]]]] = ContextVar("blocks_journal", default=None)


@contextmanager
def journal() -> Iterator[List[Dict[str, Any]]]:
    """Collects the writes made inside it: [{op, coll, id, before}], oldest first."""
    token = _journal.set([])
    try:
        yield _journal.get()
    finally:
        _journal.reset(token)


def noted(op: str, name: str, doc_id: str, handle=None) -> None:
    """Note a write. For "updated" / "deleted" pass the handle: the row as it is now is
    kept (without its vector) to put back."""
    entries = _journal.get()
    if entries is None or not doc_id:
        return
    before = None
    if op != "created" and handle is not None:
        before = handle.find_one({"_id": doc_id}, {"embedding": 0, "user_id": 0})
        if before is None:
            return
    entries.append({"op": op, "coll": name, "id": doc_id, "before": before})


def undo(effects: List[Dict[str, Any]], mongo_db=None) -> int:
    """Takes back a turn's writes, newest first: created rows go, changed rows get their
    old values back, deleted rows come back. The count of rows put right."""
    done = 0
    for e in reversed(effects or []):
        handle = coll(e.get("coll", ""), mongo_db)
        if handle is None or e.get("coll") not in (ENTRIES, ITEMS, SCHEDULES):
            continue
        before = e.get("before")
        if e.get("op") == "created":
            done += handle.delete_one({"_id": e["id"]}).deleted_count
        elif e.get("op") == "updated" and before:
            done += handle.replace_one({"_id": e["id"]}, before).matched_count
        elif e.get("op") == "deleted" and before and handle.find_one({"_id": e["id"]}, {"_id": 1}) is None:
            handle.insert_one(before)
            done += 1
    return done


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
