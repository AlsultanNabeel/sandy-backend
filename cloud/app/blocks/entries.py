"""LOG block (sandy_entries): everything that happened, or that Sandy learned.

{user_id, kind, text, data, at, source, embedding, migrated_from}
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional, Tuple

from app.blocks import _base
from app.blocks.kinds import LOG, validate
from app.integrations import embeddings

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
    return embeddings.embed(text)


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
    _base.noted("created", _base.ENTRIES, doc["_id"], text=doc["text"])
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
        _base.noted("updated", _base.ENTRIES, entry_id, coll)
        coll.update_one({"_id": entry_id}, {"$set": changes})
        if current["kind"] == "fact":
            _base.fact_changed()
    return True


def delete(entry_id: str, mongo_db=None) -> bool:
    coll = _base.coll(_base.ENTRIES, mongo_db)
    if coll is None or not entry_id:
        return False
    current = coll.find_one({"_id": entry_id}, {"kind": 1})
    _base.noted("deleted", _base.ENTRIES, entry_id, coll)
    gone = coll.delete_one({"_id": entry_id}).deleted_count > 0
    if gone and (current or {}).get("kind") == "fact":
        _base.fact_changed()
    return gone


def list_entries(kind: Optional[str] = None, *, since: Optional[datetime] = None,
                 until: Optional[datetime] = None, text: str = "",
                 exclude: Tuple[str, ...] = (),
                 limit: int = 100, mongo_db=None) -> List[Dict[str, Any]]:
    """Newest first; every filter optional. ``exclude`` drops kinds when no kind is given."""
    coll = _base.coll(_base.ENTRIES, mongo_db)
    if coll is None:
        return []
    query: Dict[str, Any] = {}
    if kind:
        query["kind"] = kind
    elif exclude:
        query["kind"] = {"$nin": list(exclude)}
    rng = _base.range_filter(since, until)
    if rng:
        query["at"] = rng
    if text:
        query.update(_base.text_filter(text))
    cursor = coll.find(query, {"embedding": 0}).sort("at", -1).limit(_base.clamp(limit))
    return [_base.out(d) for d in cursor]


def each_in_range(kind: str, *, since: Optional[datetime] = None,
                  until: Optional[datetime] = None, mongo_db=None) -> Iterator[Dict[str, Any]]:
    """Every entry of a kind in the range, newest first, with no row cap: for totals that
    must cover the whole period (a capped read summed only the part that fit)."""
    coll = _base.coll(_base.ENTRIES, mongo_db)
    if coll is None:
        return
    query: Dict[str, Any] = {"kind": kind}
    rng = _base.range_filter(since, until)
    if rng:
        query["at"] = rng
    for d in coll.find(query, {"embedding": 0}).sort("at", -1):
        yield _base.out(d)


def stats(days: int = 30, *, now: Optional[datetime] = None, mongo_db=None) -> Dict[str, Any]:
    """The My Life numbers over the whole log, in the user's zone: how many entries each
    of the last ``days`` days holds (oldest first), and this month's spending (in all
    and per category), habit check-ins and entries. Chat summaries are left out."""
    from datetime import timedelta

    from app.utils.time import USER_TZ

    local_now = (now or _base.now()).astimezone(USER_TZ)
    today = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    first_day = today - timedelta(days=days - 1)
    month_start = today.replace(day=1)
    out: Dict[str, Any] = {"days": [0] * days, "spent": 0.0, "habits": 0, "logged": 0,
                           "by_category": {}}
    coll = _base.coll(_base.ENTRIES, mongo_db)
    if coll is None:
        return out
    since = min(first_day, month_start)
    rows = coll.find({"kind": {"$ne": "summary"}, "at": {"$gte": since}},
                     {"_id": 0, "kind": 1, "at": 1, "data.amount": 1, "data.category": 1})
    for row in rows:
        at = row.get("at")
        if not isinstance(at, datetime):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)  # Mongo hands back naive UTC
        at = at.astimezone(USER_TZ)
        index = (at.date() - first_day.date()).days
        if 0 <= index < days:
            out["days"][index] += 1
        if at >= month_start:
            out["logged"] += 1
            if row.get("kind") == "habit":
                out["habits"] += 1
            amount = (row.get("data") or {}).get("amount")
            if row.get("kind") == "expense" and isinstance(amount, (int, float)):
                out["spent"] += float(amount)
                category = str((row.get("data") or {}).get("category") or "other")
                out["by_category"][category] = out["by_category"].get(category, 0.0) + float(amount)
    return out
