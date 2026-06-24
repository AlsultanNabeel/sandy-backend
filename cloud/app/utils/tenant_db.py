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
    ``self._tenant`` is always a non-empty id. Every filter gets ``user_id``
    forced to that tenant, and every inserted document gets it stamped on — a
    caller cannot widen the scope or write to another tenant even by passing an
    explicit ``user_id`` (the tenant value always wins).
    """

    __slots__ = ("_raw", "_tenant")

    def __init__(self, raw: Any, tenant: str):
        self._raw = raw
        self._tenant = tenant

    def _scope(self, filter: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        """Force this tenant onto a query filter (overriding any passed user_id)."""
        scoped = dict(filter or {})
        scoped["user_id"] = self._tenant
        return scoped

    def _stamp(self, doc: Mapping[str, Any]) -> Dict[str, Any]:
        """Stamp this tenant onto a document being inserted."""
        stamped = dict(doc)
        stamped["user_id"] = self._tenant
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
        # another tenant's documents.
        scoped_pipeline = [{"$match": {"user_id": self._tenant}}, *(pipeline or [])]
        return self._raw.aggregate(scoped_pipeline, *args, **kwargs)

    # ── writes ───────────────────────────────────────────────────────────────
    def insert_one(self, document: Mapping[str, Any], *args, **kwargs):
        return self._raw.insert_one(self._stamp(document), *args, **kwargs)

    def insert_many(self, documents, *args, **kwargs):
        return self._raw.insert_many(
            [self._stamp(d) for d in documents], *args, **kwargs
        )

    def update_one(self, filter: Mapping[str, Any], update, *args, **kwargs):
        return self._raw.update_one(self._scope(filter), update, *args, **kwargs)

    def update_many(self, filter: Mapping[str, Any], update, *args, **kwargs):
        return self._raw.update_many(self._scope(filter), update, *args, **kwargs)

    def replace_one(self, filter: Mapping[str, Any], replacement, *args, **kwargs):
        # Keep the tenant on the replacement too — a replace must not strip it.
        return self._raw.replace_one(
            self._scope(filter), self._stamp(replacement), *args, **kwargs
        )

    def delete_one(self, filter: Mapping[str, Any], *args, **kwargs):
        return self._raw.delete_one(self._scope(filter), *args, **kwargs)

    def delete_many(self, filter: Mapping[str, Any], *args, **kwargs):
        return self._raw.delete_many(self._scope(filter), *args, **kwargs)

    def find_one_and_update(self, filter: Mapping[str, Any], update, *args, **kwargs):
        # On upsert, pymongo seeds the new doc from the filter's equality terms,
        # so scoping the filter also stamps the tenant onto an upserted document.
        return self._raw.find_one_and_update(
            self._scope(filter), update, *args, **kwargs
        )

    def find_one_and_delete(self, filter: Mapping[str, Any], *args, **kwargs):
        return self._raw.find_one_and_delete(self._scope(filter), *args, **kwargs)


def scoped(mongo_db: Any, name: str) -> Optional[ScopedCollection]:
    """Return a tenant-scoped view of ``mongo_db[name]``, or ``None`` when there
    is no database handle or no active tenant (fail-closed). Callers already
    guard ``if coll is None`` — that guard now also blocks unauthenticated access.
    """
    if mongo_db is None:
        return None
    tenant = current_user_id()
    if not tenant:
        return None
    return ScopedCollection(mongo_db[name], tenant)
