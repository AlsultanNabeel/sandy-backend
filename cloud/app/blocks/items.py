"""LISTS block (sandy_items): anything you tick off.

{user_id, list, text, done, due, priority, data, created_at, done_at, migrated_from}
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from app.blocks import _base
from app.blocks.kinds import LIST, validate

logger = logging.getLogger(__name__)


def init_items_store(mongo_db) -> None:
    if mongo_db is None:
        return
    for keys in ([("user_id", 1), ("list", 1), ("done", 1), ("created_at", 1)],
                 [("user_id", 1), ("due", 1)],
                 [("user_id", 1), ("migrated_from.collection", 1), ("migrated_from.id", 1)]):
        try:
            mongo_db[_base.ITEMS].create_index(keys, background=True)
        except Exception as exc:  # noqa: BLE001 — one failed index must not skip the rest
            logger.warning("[blocks] items index %s skipped: %s", keys, exc)


def add(list_name: str, text: str, data: Optional[Mapping[str, Any]] = None, *,
        done: bool = False, due: Optional[datetime] = None, priority: str = "",
        created_at: Optional[datetime] = None, done_at: Optional[datetime] = None,
        migrated_from: Optional[Mapping[str, Any]] = None,
        doc_id: Optional[str] = None, mongo_db=None) -> str:
    """New item id, or "" with no tenant. Bad list/data raises KindError."""
    clean = validate(LIST, list_name, data)
    coll = _base.coll(_base.ITEMS, mongo_db)
    if coll is None:
        return ""
    done = bool(done)
    doc = {
        "_id": doc_id or _base.new_id(),
        "list": list_name,
        "text": str(text or "").strip(),
        "done": done,
        "due": due,
        "priority": str(priority or "").strip(),
        "data": clean,
        "created_at": created_at or _base.now(),
        "done_at": (done_at or _base.now()) if done else None,
        "migrated_from": _base.migrated_ref(migrated_from),
    }
    coll.insert_one(doc)
    return doc["_id"]


def get(item_id: str, mongo_db=None) -> Optional[Dict[str, Any]]:
    coll = _base.coll(_base.ITEMS, mongo_db)
    if coll is None or not item_id:
        return None
    return _base.out(coll.find_one({"_id": item_id}))


_UNSET = object()


def update(item_id: str, *, text: Optional[str] = None, done: Optional[bool] = None,
           due: Any = _UNSET, priority: Optional[str] = None,
           data: Optional[Mapping[str, Any]] = None, mongo_db=None) -> bool:
    """Change fields; ``due=None`` clears it. True when the item exists."""
    coll = _base.coll(_base.ITEMS, mongo_db)
    if coll is None or not item_id:
        return False
    current = coll.find_one({"_id": item_id}, {"list": 1})
    if current is None:
        return False
    changes: Dict[str, Any] = {}
    if text is not None:
        changes["text"] = str(text).strip()
    if done is not None:
        changes["done"] = bool(done)
        changes["done_at"] = _base.now() if done else None
    if due is not _UNSET:
        changes["due"] = due
    if priority is not None:
        changes["priority"] = str(priority).strip()
    if data is not None:
        changes["data"] = validate(LIST, current["list"], data)
    if changes:
        coll.update_one({"_id": item_id}, {"$set": changes})
    return True


def delete(item_id: str, mongo_db=None) -> bool:
    coll = _base.coll(_base.ITEMS, mongo_db)
    if coll is None or not item_id:
        return False
    return coll.delete_one({"_id": item_id}).deleted_count > 0


def list_items(list_name: Optional[str] = None, *, done: Optional[bool] = None,
               due_after: Optional[datetime] = None, due_before: Optional[datetime] = None,
               text: str = "", limit: int = 200, mongo_db=None) -> List[Dict[str, Any]]:
    """Oldest first, the order a list is read in; every filter optional."""
    coll = _base.coll(_base.ITEMS, mongo_db)
    if coll is None:
        return []
    query: Dict[str, Any] = {}
    if list_name:
        query["list"] = list_name
    if done is not None:
        query["done"] = bool(done)
    rng = _base.range_filter(due_after, due_before)
    if rng:
        query["due"] = rng
    if text:
        query.update(_base.text_filter(text))
    cursor = coll.find(query).sort("created_at", 1).limit(_base.clamp(limit))
    return [_base.out(d) for d in cursor]
