"""Tenant-scoped data access — the single enforced isolation boundary.

Every data operation goes through a ScopedCollection that forces the caller's
tenant onto filters and inserted documents. ``scoped()`` returns None with no
database or no authenticated tenant, so the store's ``if coll is None`` guard
fails closed. Indexes are created on the raw handle at boot, before any tenant.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.utils.user_profiles import current_user_id


class ScopedCollection:
    """A pymongo collection whose every operation is forced onto one tenant.

    The tenant value always wins over a caller-supplied scope field, in filters,
    inserts and update operators alike.
    """

    __slots__ = ("_raw", "_tenant", "_field", "_bump")

    def __init__(self, raw: Any, tenant: str, field: str = "user_id",
                 bump: bool = True):
        self._raw = raw
        self._tenant = tenant
        self._field = field
        self._bump = bump

    @property
    def tenant(self) -> str:
        """For a ``$vectorSearch`` filter, which must run on the raw collection."""
        return self._tenant

    def _scope(self, filter: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
        scoped = dict(filter or {})
        scoped[self._field] = self._tenant
        return scoped

    def _stamp(self, doc: Mapping[str, Any]) -> Dict[str, Any]:
        stamped = dict(doc)
        stamped[self._field] = self._tenant
        return stamped

    _ASSIGN_OPS = ("$set", "$setOnInsert")
    _REMOVE_OPS = ("$unset", "$rename")

    def _guard_update(self, update: Any) -> Any:
        """Stop an update from reassigning or removing the scope field.

        Assignments are rewritten to this tenant; $unset/$rename of it are dropped.
        """
        if isinstance(update, Mapping):
            return self._guard_operators(update)
        if isinstance(update, list):
            return [self._guard_stage(st) if isinstance(st, Mapping) else st
                    for st in update]
        return update

    def _guard_operators(self, update: Mapping[str, Any]) -> Dict[str, Any]:
        out = dict(update)
        for op in self._ASSIGN_OPS:
            if isinstance(out.get(op), Mapping) and self._field in out[op]:
                out[op] = {**out[op], self._field: self._tenant}
        for op in self._REMOVE_OPS:
            if isinstance(out.get(op), Mapping) and self._field in out[op]:
                out[op] = {k: v for k, v in out[op].items() if k != self._field}
                if not out[op]:
                    del out[op]
        if update and not out:
            # The whole update only stripped the tenant; fail loudly.
            raise ValueError(
                f"update would only remove the tenant field {self._field!r}")
        return out

    _PIPELINE_STAGES_GUARDED = ("$set", "$addFields", "$unset")

    def _guard_stage(self, stage: Mapping[str, Any]) -> Dict[str, Any]:
        """Guard one pipeline-update stage; allowlist only.

        $project/$replaceRoot/$replaceWith can rewrite the whole document and
        cannot be made safe, so they are refused.
        """
        out = dict(stage)
        for op in ("$set", "$addFields"):
            if isinstance(out.get(op), Mapping) and self._field in out[op]:
                out[op] = {**out[op], self._field: self._tenant}

        if "$unset" in out:
            unset = out["$unset"]
            # A mapping is illegal here, but still must not let the field through.
            if isinstance(unset, str):
                remaining: Any = None if unset == self._field else unset
            elif isinstance(unset, list):
                kept = [f for f in unset if f != self._field]
                remaining = kept or None
            elif isinstance(unset, Mapping):
                kept_map = {k: v for k, v in unset.items() if k != self._field}
                remaining = kept_map or None
            else:
                remaining = unset
            if remaining is None:
                del out["$unset"]
            else:
                out["$unset"] = remaining

        unknown = [op for op in out if op not in self._PIPELINE_STAGES_GUARDED]
        if unknown:
            raise ValueError(
                f"pipeline stage(s) {unknown!r} cannot be tenant-guarded; express "
                f"the change with $set/$addFields/$unset only, so {self._field!r} "
                f"stays under this collection's control")
        if stage and not out:
            raise ValueError(
                f"pipeline stage would only remove the tenant field {self._field!r}")
        return out

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
        # Not usable for $vectorSearch (must be stage one); filter inside it on the raw collection.
        scoped_pipeline = [{"$match": {self._field: self._tenant}}, *(pipeline or [])]
        return self._raw.aggregate(scoped_pipeline, *args, **kwargs)

    # ── writes ───────────────────────────────────────────────────────────────
    # Every write marks the tenant's cached context stale (utils/tenant_version.py).
    def _note_write(self) -> None:
        if not self._bump:
            return
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
        out = self._raw.update_one(
            self._scope(filter), self._guard_update(update), *args, **kwargs)
        self._note_write()
        return out

    def update_many(self, filter: Mapping[str, Any], update, *args, **kwargs):
        out = self._raw.update_many(
            self._scope(filter), self._guard_update(update), *args, **kwargs)
        self._note_write()
        return out

    def replace_one(self, filter: Mapping[str, Any], replacement, *args, **kwargs):
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
        # On upsert the scoped filter also stamps the tenant onto the new doc.
        out = self._raw.find_one_and_update(
            self._scope(filter), self._guard_update(update), *args, **kwargs
        )
        self._note_write()
        return out

    def find_one_and_delete(self, filter: Mapping[str, Any], *args, **kwargs):
        out = self._raw.find_one_and_delete(self._scope(filter), *args, **kwargs)
        self._note_write()
        return out

    def insert_missing(self, documents: List[Mapping[str, Any]]) -> int:
        """Insert documents whose ``_id`` is new, in one round trip; returns the count inserted.

        Not a general bulk_write: scoping arbitrary pymongo ops would depend on
        driver internals. Unordered, so duplicate keys from a race skip only themselves.
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
            errors = (exc.details or {}).get("writeErrors") or []
            if errors and all(e.get("code") == 11000 for e in errors):
                return len(docs) - len(errors)
            raise


def scoped(mongo_db: Any, name: str, field: str = "user_id",
           bump: bool = True) -> Optional[ScopedCollection]:
    """Tenant-scoped ``mongo_db[name]``, or None with no db or no tenant (fail closed).

    ``field="chat_id"`` for older collections. ``bump=False`` only for per-turn
    writers that feed nothing cached (else the cache is invalidated every message).
    """
    if mongo_db is None:
        return None
    tenant = current_user_id()
    if not tenant:
        return None
    return ScopedCollection(mongo_db[name], tenant, field=field, bump=bump)
