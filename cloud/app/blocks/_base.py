"""What the three block stores share: the scoped handle, filters, output shape."""

from __future__ import annotations

import re
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional

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


# ── the one way a row changes ────────────────────────────────────────────────
# A write and its event (`events`) go in one transaction: both are kept or neither is.

_session: ContextVar[Any] = ContextVar("blocks_session", default=None)


def _client(handle) -> Any:
    raw = getattr(handle, "_raw", handle)
    return raw.database.client


def _mock(client: Any) -> bool:
    """The tests' in-memory stand-in (mongomock), which has no transactions."""
    return type(client).__module__.startswith("mongomock")


def _in_transaction(handle, fn: Callable[[Any], Any]) -> Any:
    """``fn(session)`` in one transaction (inside one already open, in that one). Production's
    database is a replica set and always has them; only the tests' stand-in runs it bare."""
    open_now = _session.get()
    if open_now is not None:
        return fn(open_now)
    client = _client(handle)
    if _mock(client):
        return fn(None)

    def body(session):
        token = _session.set(session)
        try:
            return fn(session)
        finally:
            _session.reset(token)

    with client.start_session() as session:
        return session.with_transaction(body)


def write(op: str, name: str, doc_id: str, handle, apply: Callable[[Any], Any], *,
          created: Optional[Dict[str, Any]] = None, text: str = "") -> Any:
    """The one way a block row changes: ``apply(session)`` and its event in one transaction,
    then the turn's journal and the undo log (`noted`). ``created`` is the new row of an
    add. What ``apply`` returns comes back."""
    from app.blocks import events

    def run(session):
        before = None
        if op != "created":
            before = handle.find_one({"_id": doc_id}, {"embedding": 0, "user_id": 0}, session=session)
        out = apply(session)
        after = created if op == "created" else (
            handle.find_one({"_id": doc_id}, {"embedding": 0, "user_id": 0}, session=session)
            if op == "updated" else None)
        # A row copied in from the old stores (`migrated_from`) is no change he made.
        if (op == "created" or before is not None) and not (created or {}).get("migrated_from"):
            events.add(name, op, doc_id, before, after, session=session)
        return out, before

    out, before = _in_transaction(handle, run)
    if op == "created" or before is not None:
        noted(op, name, doc_id, before=before, text=text)
    return out


def noted(op: str, name: str, doc_id: str, before: Optional[Dict[str, Any]] = None,
          text: str = "") -> None:
    """Note a write, with the row as it was (``before``, without its vector) to put back. A
    created row's `text` names it in an undo. It goes to the turn's journal when one is
    open, and to `changes` (a delete always, so every delete can be put back for seven days)."""
    from app.blocks import changes

    entries = _journal.get()
    keeping = op == "deleted" or changes.current_turn() is not None
    if (entries is None and not keeping) or not doc_id:
        return
    label = text or str((before or {}).get("text") or "")
    if entries is not None:
        entries.append({"op": op, "coll": name, "id": doc_id, "before": before, "text": label})
    if keeping:
        changes.keep(op, name, doc_id, before, label)


def fact_changed() -> None:
    """A `fact` entry was edited or removed: the voice instruction that carries the facts
    must not be served from before it (`tenant_version.mark_corrected`)."""
    from app.utils.tenant_version import mark_corrected
    from app.utils.user_profiles import current_user_id

    mark_corrected(current_user_id() or "")


def _with_vector(row: Dict[str, Any]) -> Dict[str, Any]:
    """A log row put back by undo gets its vector again (the journal keeps it without one,
    and a row with none is never found by meaning). Sealed rows are never embedded."""
    if (row.get("data") or {}).get("encrypted"):
        return row
    from app.blocks.entries import embed_text

    return {**row, "embedding": embed_text(str(row.get("text") or ""))}


def undo(effects: List[Dict[str, Any]], mongo_db=None) -> int:
    """Takes back a turn's writes, newest first: created rows go, changed rows get their
    old values back, deleted rows come back. The count of rows put right."""
    done = 0
    facts = False
    for e in reversed(effects or []):
        handle = coll(e.get("coll", ""), mongo_db)
        if handle is None or e.get("coll") not in (ENTRIES, ITEMS, SCHEDULES):
            continue
        before = e.get("before")
        if e.get("coll") == ENTRIES and not facts:
            row = before or handle.find_one({"_id": e["id"]}, {"kind": 1}) or {}
            facts = row.get("kind") == "fact"
        if e.get("op") != "created" and before and e.get("coll") == ENTRIES:
            before = _with_vector(before)
        if before and e.get("coll") == SCHEDULES:
            # No phone holds a reminder put back until it says so (`schedules.arm`).
            before = {**before, "armed": [], "armed_once": []}
        if e.get("op") == "created":
            done += handle.delete_one({"_id": e["id"]}).deleted_count
        elif e.get("op") == "updated" and before:
            done += handle.replace_one({"_id": e["id"]}, before).matched_count
        elif e.get("op") == "deleted" and before and handle.find_one({"_id": e["id"]}, {"_id": 1}) is None:
            handle.insert_one(before)
            done += 1
    if facts:
        fact_changed()
    if any(e.get("coll") == SCHEDULES for e in effects or []):
        # A reminder put back or taken away must reach the phone too.
        from app.services import schedule_sync
        schedule_sync.changed()
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
