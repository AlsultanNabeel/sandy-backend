"""The Atlas vector index on sandy_entries: made when missing, never touched when there,
made at boot without holding it up, and a search that finds nothing because of it says so."""
from __future__ import annotations

import logging
import threading

from pymongo.errors import OperationFailure

from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import entries, vector_index
from app.brain import context
from app.utils.tenant_db import ScopedCollection
from app.utils.user_profiles import active_user_profile_context

READY = {"name": "entries_vector", "type": "vectorSearch", "status": "READY", "queryable": True}


class _Entries:
    """sandy_entries as Atlas shows its search indexes."""

    def __init__(self, indexes=(), refuse=None):
        self.indexes = list(indexes)
        self.refuse = refuse
        self.created = []

    def list_search_indexes(self, name=None):
        return [ix for ix in self.indexes if name is None or ix["name"] == name]

    def create_search_index(self, model):
        if self.refuse:
            raise self.refuse
        self.created.append(model.document)
        return model.document["name"]


def _db(coll):
    return {"sandy_entries": coll}


def test_an_index_that_is_there_is_not_touched():
    coll = _Entries([READY])
    assert vector_index.ensure(_db(coll)) == "present"
    assert coll.created == []


def test_a_missing_index_is_made_with_the_same_definition():
    coll = _Entries()
    assert vector_index.ensure(_db(coll)) == "created"
    assert coll.created == [{
        "name": "entries_vector", "type": "vectorSearch",
        "definition": {"fields": [
            {"type": "vector", "path": "embedding", "numDimensions": 1536, "similarity": "cosine"},
            {"type": "filter", "path": "user_id"},
            {"type": "filter", "path": "kind"},
        ]},
    }]


def test_a_failed_create_at_boot_warns_and_carries_on(caplog):
    coll = _Entries(refuse=OperationFailure("not on Atlas"))
    with caplog.at_level(logging.WARNING, logger="app.blocks.vector_index"):
        vector_index.ensure_in_background(_db(coll)).result(5)
    assert any("entries_vector" in r.getMessage() and "not on Atlas" in r.getMessage()
               for r in caplog.records)


def test_boot_does_not_wait_for_it():
    release = threading.Event()

    class _Slow(_Entries):
        def list_search_indexes(self, name=None):
            release.wait(5)
            return []

    worker = vector_index.ensure_in_background(_db(_Slow()))
    assert not worker.done()          # returned while Atlas is still answering
    release.set()
    worker.result(5)


def test_bootstrap_starts_it(monkeypatch):
    from app import bootstrap, config, db as appdb
    from app.utils import process_leader

    started = []
    monkeypatch.setattr(config, "validate_config", lambda: ([], []))
    monkeypatch.setattr(process_leader, "claim_leadership", lambda name: False)
    monkeypatch.setattr(vector_index, "ensure_in_background", started.append)
    # The boot guard marks the database first (`utils/env_guard.py`).
    import mongomock
    appdb.configure({**_db(_Entries([READY])), "sandy_env": mongomock.MongoClient().db["sandy_env"]})
    try:
        bootstrap.bootstrap(app_env="test")
    finally:
        appdb.reset()
    assert len(started) == 1


def _search_finds_nothing(monkeypatch, indexes):
    monkeypatch.setattr(vector_index, "_ready", False)
    monkeypatch.setattr(ScopedCollection, "vector_search", lambda self, *a, **kw: [])
    monkeypatch.setattr(ScopedCollection, "search_index",
                        lambda self, name: next((ix for ix in indexes if ix["name"] == name), None))
    monkeypatch.setattr(entries, "embed_text", lambda text: [0.9, 0.1])
    with active_user_profile_context(A):
        entries.add("journal", "رحت عالبحر مع صحابي")
        return [e["text"] for e in context.similar_entries("بدي أروح عالبحر بكرا")]


def test_a_missing_index_is_named_in_the_log_not_skipped_silently(brain_db, monkeypatch, caplog):  # noqa: F811
    with caplog.at_level(logging.WARNING, logger="app.brain.context"):
        rows = _search_finds_nothing(monkeypatch, [])
    assert rows == ["رحت عالبحر مع صحابي"]          # the words still answer
    assert any("entries_vector" in r.getMessage() and "missing" in r.getMessage()
               for r in caplog.records)


def test_an_index_still_building_is_named_too(brain_db, monkeypatch, caplog):  # noqa: F811
    building = {**READY, "status": "BUILDING", "queryable": False}
    with caplog.at_level(logging.WARNING, logger="app.brain.context"):
        _search_finds_nothing(monkeypatch, [building])
    assert any("entries_vector" in r.getMessage() and "BUILDING" in r.getMessage()
               for r in caplog.records)


def test_a_ready_index_that_finds_nothing_logs_nothing(brain_db, monkeypatch, caplog):  # noqa: F811
    with caplog.at_level(logging.WARNING, logger="app.brain.context"):
        _search_finds_nothing(monkeypatch, [READY])
    assert not [r for r in caplog.records if "entries_vector" in r.getMessage()]


def test_boot_says_the_index_is_there(caplog):
    with caplog.at_level(logging.INFO, logger="app.blocks.vector_index"):
        vector_index.ensure_in_background(_db(_Entries([READY]))).result(5)
    assert any("entries_vector is there" in r.getMessage() for r in caplog.records)
