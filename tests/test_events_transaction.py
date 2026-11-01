"""A change and its event are one transaction (owner, 30 Oct 2026): both are kept or neither.
On a real MongoDB replica set (`SANDY_TEST_MONGO_URI`, a single-node one locally and in CI),
since the in-memory stand-in has no transactions: an event that fails to be written leaves
the change undone, for an add, an edit and a delete, in every block."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app import db as appdb
from app.blocks import entries, events, init_blocks, items, schedules
from app.utils.user_profiles import active_user_profile_context

URI = os.getenv("SANDY_TEST_MONGO_URI", "")
if not URI and os.getenv("CI"):
    raise RuntimeError("SANDY_TEST_MONGO_URI is needed in CI: the transaction tests run on a real replica set")
pytestmark = pytest.mark.skipif(not URI, reason="no real MongoDB (SANDY_TEST_MONGO_URI)")

A = {"chat_id": "userA", "relation": "user", "permissions": "all"}


@pytest.fixture
def real(monkeypatch):
    from pymongo import MongoClient
    client = MongoClient(URI, serverSelectionTimeoutMS=5000)
    name = f"sandy_test_{uuid.uuid4().hex[:10]}"
    d = client[name]
    appdb.configure(d)
    init_blocks(d)
    monkeypatch.setattr(entries, "embed_text", lambda text: None)
    try:
        with active_user_profile_context(A):
            yield d
    finally:
        appdb.reset()
        client.drop_database(name)
        client.close()


def _broken(monkeypatch):
    def fail(*a, **k):
        raise RuntimeError("the event could not be written")
    monkeypatch.setattr(events, "add", fail)


def test_a_change_and_its_event_are_kept_together(real):
    iid = items.add("shopping", "رمان")
    items.update(iid, done=True)
    assert [e["op"] for e in events.since(0)] == ["added", "done"]
    assert real["sandy_items"].count_documents({}) == 1


@pytest.mark.parametrize("block", ["items", "entries", "schedules"])
def test_an_event_that_fails_leaves_an_add_undone(real, monkeypatch, block):
    _broken(monkeypatch)
    with pytest.raises(RuntimeError):
        if block == "items":
            items.add("shopping", "رمان")
        elif block == "entries":
            entries.add("note", "hello")
        else:
            schedules.add("reminder", "call", datetime.now(timezone.utc) + timedelta(hours=1))
    name = {"items": "sandy_items", "entries": "sandy_entries", "schedules": "sandy_schedules"}[block]
    assert real[name].count_documents({}) == 0


def test_an_event_that_fails_leaves_an_edit_and_a_delete_undone(real, monkeypatch):
    iid = items.add("shopping", "رمان")
    _broken(monkeypatch)
    with pytest.raises(RuntimeError):
        items.update(iid, done=True)
    assert real["sandy_items"].find_one({"_id": iid})["done"] is False
    with pytest.raises(RuntimeError):
        items.delete(iid)
    assert real["sandy_items"].count_documents({"_id": iid}) == 1


def test_clearing_the_done_ones_is_one_transaction(real, monkeypatch):
    """«فضّي اللي تمّ» hides them all or none (review, 1 Nov 2026): an event that fails on the
    second leaves the first not hidden either."""
    for text in ("رمان", "خبز", "حليب"):
        items.add("shopping", text, done=True)
    real_add, written = events.add, []

    def second_fails(*a, **k):
        written.append(1)
        if len(written) == 2:
            raise RuntimeError("the event could not be written")
        return real_add(*a, **k)
    monkeypatch.setattr(events, "add", second_fails)
    with pytest.raises(RuntimeError):
        items.hide_done("shopping")
    assert real["sandy_items"].count_documents({"hidden_at": {"$ne": None}}) == 0
    assert [e["op"] for e in events.since(0)] == ["added"] * 3
