"""LOG block (sandy_entries): everything that happened, or that Sandy learned.

{user_id, kind, text, data, at, source, embedding, migrated_from}
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional

from app.agent import semantic_memory
from app.blocks import _base
from app.blocks.kinds import LOG, validate

logger = logging.getLogger(__name__)

SOURCES = ("chat", "voice", "app")


def init_entries_store(mongo_db) -> None:
    if mongo_db is None:
        return
    for keys in ([("user_id", 1), ("kind", 1), ("at", -1)],
                 [("user_id", 1), ("at", -1)],
                 [("user_id", 1), ("migrated_from.collection", 1), ("migrated_from.id", 1)]):
        try:
            mongo_db[_base.ENTRIES].create_index(keys, background=True)
        except Exception as exc:  # noqa: BLE001 — one failed index must not skip the rest
            logger.warning("[blocks] entries index %s skipped: %s", keys, exc)


def embed_text(text: str) -> Optional[List[float]]:
    """The repo's one embedding helper; None when embeddings are off or fail."""
    return semantic_memory._embed(text)


def add(kind: str, text: str, data: Optional[Mapping[str, Any]] = None, *,
        at: Optional[datetime] = None, source: str = "app", embed: bool = True,
        embedding: Optional[List[float]] = None,
        migrated_from: Optional[Mapping[str, Any]] = None,
        doc_id: Optional[str] = None, mongo_db=None) -> str:
    """New entry id, or "" with no tenant. Bad kind/data raises KindError."""
    clean = validate(LOG, kind, data)
    if source not in SOURCES:
        raise ValueError(f"source must be one of {SOURCES}, got {source!r}")
    coll = _base.coll(_base.ENTRIES, mongo_db)
    if coll is None:
        return ""
    text = str(text or "").strip()
    if embedding is None and embed and text:
        embedding = embed_text(text)
    doc = {
        "_id": doc_id or _base.new_id(),
        "kind": kind,
        "text": text,
        "data": clean,
        "at": at or _base.now(),
        "source": source,
        "embedding": embedding,
        "migrated_from": _base.migrated_ref(migrated_from),
    }
    coll.insert_one(doc)
    return doc["_id"]


def get(entry_id: str, mongo_db=None) -> Optional[Dict[str, Any]]:
    coll = _base.coll(_base.ENTRIES, mongo_db)
    if coll is None or not entry_id:
        return None
    return _base.out(coll.find_one({"_id": entry_id}))


def update(entry_id: str, *, text: Optional[str] = None,
           data: Optional[Mapping[str, Any]] = None,
           at: Optional[datetime] = None, embed: bool = True, mongo_db=None) -> bool:
    """Change text / data (replaced whole) / at; True when the entry exists."""
    coll = _base.coll(_base.ENTRIES, mongo_db)
    if coll is None or not entry_id:
        return False
    current = coll.find_one({"_id": entry_id}, {"kind": 1})
    if current is None:
        return False
    changes: Dict[str, Any] = {}
    if text is not None:
        changes["text"] = str(text).strip()
        # A stale vector would keep matching the old wording.
        changes["embedding"] = embed_text(changes["text"]) if embed else None
    if data is not None:
        changes["data"] = validate(LOG, current["kind"], data)
    if at is not None:
        changes["at"] = at
    if changes:
        coll.update_one({"_id": entry_id}, {"$set": changes})
    return True


def delete(entry_id: str, mongo_db=None) -> bool:
    coll = _base.coll(_base.ENTRIES, mongo_db)
    if coll is None or not entry_id:
        return False
    return coll.delete_one({"_id": entry_id}).deleted_count > 0


def list_entries(kind: Optional[str] = None, *, since: Optional[datetime] = None,
                 until: Optional[datetime] = None, text: str = "",
                 limit: int = 100, mongo_db=None) -> List[Dict[str, Any]]:
    """Newest first; every filter optional."""
    coll = _base.coll(_base.ENTRIES, mongo_db)
    if coll is None:
        return []
    query: Dict[str, Any] = {}
    if kind:
        query["kind"] = kind
    rng = _base.range_filter(since, until)
    if rng:
        query["at"] = rng
    if text:
        query.update(_base.text_filter(text))
    cursor = coll.find(query, {"embedding": 0}).sort("at", -1).limit(_base.clamp(limit))
    return [_base.out(d) for d in cursor]
