"""Tenant-scoped data access — the single enforced isolation boundary.

Multi-tenant isolation used to live as a hand-written ``{"user_id": uid}`` filter
inside every store function. That is fragile by construction: one forgotten
filter is a cross-tenant leak (exactly the class of bug that let a non-owner
drive the owner's room). This module removes the choice — every data operation
goes through a :class:`ScopedCollection` that stamps the caller's tenant onto the
query and the inserted document automatically, so no store *can* read or write
outside its tenant.

How it fails closed
-------------------
``scoped(mongo_db, name)`` returns ``None`` when there is no Mongo handle **or no
active tenant** (``current_user_id()`` is None — an unauthenticated context).
Every store already guards ``if coll is None: return <safe default>``, so that
one guard now covers *both* "no database" and "no tenant" — a context without an
authenticated user reads nothing and writes nothing.

Usage (drop-in for a raw pymongo collection on the data path)::

    from app.utils.tenant_db import scoped

    def _coll():
        return scoped(_mongo_db, _COLL)   # None when no db / no tenant

    coll = _coll()
    if coll is None:
        return []
    coll.find({"done": False})            # user_id injected automatically
    coll.insert_one({"text": "..."})      # user_id stamped automatically

Index creation stays on the raw handle at boot (``mongo_db[name].create_index``):
indexes already lead with ``user_id`` and run before any request sets a tenant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.utils.user_profiles import current_user_id


class ScopedCollection:
    """A pymongo collection that auto-scopes every operation to one tenant.

    Constructed only when a tenant is present (see :func:`scoped`), so
    ``self._tenant`` is always a non-empty id. Every filter gets the scope
    field (``user_id`` by default; some legacy collections key on ``chat_id``
    instead — pass ``field=`` to match) forced to that tenant, and every
    inserted document gets it stamped on — a caller cannot widen the scope or
    write to another tenant even by passing an explicit value for that field
    (the tenant value always wins).
    """

    __slots__ = ("_raw", "_tenant", "_field")

    def __init__(self, raw: Any, tenant: str, field: str = "user_id"):
        self._raw = raw
        self._tenant = tenant
        self._field = field

    @property
    def tenant(self) -> str:
        """The tenant id this collection is scoped to — for the rare caller
        that needs it directly (e.g. embedding it in a ``$vectorSearch``
        filter, which must run against the raw collection)."""
        return self._tenant

    def _scope(self, filter: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        """Force this tenant onto a query filter (overriding any passed value)."""
        scoped = dict(filter or {})
        scoped[self._field] = self._tenant
        return scoped

    def _stamp(self, doc: Mapping[str, Any]) -> Dict[str, Any]:
        """Stamp this tenant onto a document being inserted."""
        stamped = dict(doc)
        stamped[self._field] = self._tenant
        return stamped

    # ── reads ────────────────────────────────────────────────────────────────
    def find(self, filter: Optional[Mapping[str, Any]] = None, *args, **kwargs):
        return self._raw.find(self._scope(filter), *args, **kwargs)

    def find_one(self, filter: Optional[Mapping[str, Any]] = None, *args, **kwargs):
        return self._raw.find_one(self._scope(filter), *args, **kwargs)

    def count_documents(self, filter: Optional[Mapping[str, Any]] = None, *args, **kwargs):
        return self._raw.count_documents(self._scope(filter), *args, **kwargs)

    def distinct(self, key: str, filter: Optional[Mapping[str, Any]] = None, *args, **kwargs):
        return self._raw.distinct(key, self._scope(filter), *args, **kwargs)

    def aggregate(self, pipeline: List[Mapping[str, Any]], *args, **kwargs):
        # Force a tenant $match as the first stage so no later stage can surface
        # another tenant's documents. NOTE: not usable for a $vectorSearch
        # pipeline — Atlas requires $vectorSearch to be stage one, so that case
        # must filter inside the $vectorSearch stage itself and aggregate on
        # the raw collection (use `.tenant` to source the id consistently).
        scoped_pipeline = [{"$match": {self._field: self._tenant}}, *(pipeline or [])]
        return self._raw.aggregate(scoped_pipeline, *args, **kwargs)

    # ── writes ───────────────────────────────────────────────────────────────
    #
    # Every write marks the tenant's cached context stale — see
    # `utils/tenant_version.py`. Here because this class is what most tenant
    # writes already pass through; the handful that reach past it call
    # `bump_for` themselves, and those are named in that module.
    def _note_write(self) -> None:
        from app.utils.tenant_version import bump_for

        bump_for(self._tenant, collection=getattr(self._raw, "name", ""))

    def insert_one(self, document: Mapping[str, Any], *args, **kwargs):
        out = self._raw.insert_one(self._stamp(document), *args, **kwargs)
        self._note_write()
        return out

    def insert_many(self, documents, *args, **kwargs):
        out = self._raw.insert_many(
            [self._stamp(d) for d in documents], *args, **kwargs
        )
        self._note_write()
        return out

    def update_one(self, filter: Mapping[str, Any], update, *args, **kwargs):
        out = self._raw.update_one(self._scope(filter), update, *args, **kwargs)
        self._note_write()
        return out

    def update_many(self, filter: Mapping[str, Any], update, *args, **kwargs):
        out = self._raw.update_many(self._scope(filter), update, *args, **kwargs)
        self._note_write()
        return out

    def replace_one(self, filter: Mapping[str, Any], replacement, *args, **kwargs):
        # Keep the tenant on the replacement too — a replace must not strip it.
        out = self._raw.replace_one(
            self._scope(filter), self._stamp(replacement), *args, **kwargs
        )
        self._note_write()
        return out

    def delete_one(self, filter: Mapping[str, Any], *args, **kwargs):
        out = self._raw.delete_one(self._scope(filter), *args, **kwargs)
        self._note_write()
        return out

    def delete_many(self, filter: Mapping[str, Any], *args, **kwargs):
        out = self._raw.delete_many(self._scope(filter), *args, **kwargs)
        self._note_write()
        return out

    def find_one_and_update(self, filter: Mapping[str, Any], update, *args, **kwargs):
        # On upsert, pymongo seeds the new doc from the filter's equality terms,
        # so scoping the filter also stamps the tenant onto an upserted document.
        out = self._raw.find_one_and_update(
            self._scope(filter), update, *args, **kwargs
        )
        self._note_write()
        return out

    def find_one_and_delete(self, filter: Mapping[str, Any], *args, **kwargs):
        out = self._raw.find_one_and_delete(self._scope(filter), *args, **kwargs)
        self._note_write()
        return out

    def insert_missing(self, documents: List[Mapping[str, Any]]) -> int:
        """Insert each document if its ``_id`` is absent — **one round trip**.
        Returns how many were actually new.

        There was no bulk write on this class at all, which was safe by accident
        rather than by design: an unscoped one is precisely the hole this class
        exists to close, and it was closed by `AttributeError`. But "one document
        per round trip" is a real cost, and the caller that hit it
        (`semantic_memory.load_facts_to_chroma`) was re-indexing a person's whole
        life an item at a time on a path that runs every message.

        **Deliberately not a general `bulk_write`.** Scoping arbitrary pymongo
        operation objects means reading their private attributes to rebuild them,
        which ties the isolation boundary — the most important code in the repo —
        to internals that change between driver releases. This takes plain
        documents and builds the operations itself, so there is nothing to
        misread and no way to hand it an operation it does not understand.

        Each document keeps its own ``_id`` and is stamped with the tenant, so a
        batch cannot write outside its tenant any more than ``insert_one`` could.

        Built on ``insert_many(ordered=False)`` rather than a bulk upsert:
        "insert what is missing" is what the caller means, and an unordered
        insert already has the right behaviour for the race — if another writer
        got there first, that one document is refused as a duplicate key and the
        rest still land. `ordered=False` is what makes the batch continue past
        it instead of stopping at the first collision.
        """
        docs = [self._stamp(d) for d in documents if d.get("_id") is not None]
        if not docs:
            return 0
        from pymongo.errors import BulkWriteError

        try:
            result = self._raw.insert_many(docs, ordered=False)
            self._note_write()
            return len(getattr(result, "inserted_ids", None) or [])
        except BulkWriteError as exc:
            # A duplicate key here is the expected outcome of a race, not a
            # failure: someone else inserted the same id between our existence
            # check and this write. Any other write error still propagates.
            errors = (exc.details or {}).get("writeErrors") or []
            if errors and all(e.get("code") == 11000 for e in errors):
                return len(docs) - len(errors)
            raise


def scoped(mongo_db: Any, name: str, field: str = "user_id") -> Optional[ScopedCollection]:
    """Return a tenant-scoped view of ``mongo_db[name]``, or ``None`` when there
    is no database handle or no active tenant (fail-closed). Callers already
    guard ``if coll is None`` — that guard now also blocks unauthenticated access.

    ``field`` is the scope field to stamp/filter on. Defaults to ``user_id``;
    pass ``field="chat_id"`` for the older collections (semantic memory) that
    predate that naming.
    """
    if mongo_db is None:
        return None
    tenant = current_user_id()
    if not tenant:
        return None
    return ScopedCollection(mongo_db[name], tenant, field=field)
