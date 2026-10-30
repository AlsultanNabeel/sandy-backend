"""The log of what happened to his data (`blocks/events.py`): each change to an item, an
entry or a schedule is one event, with what it was and what it is, in his own order; sealed
words stay sealed; a copied-in row is no event; it lives ninety days and goes with him."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, B, brain_db  # noqa: F401

from app.blocks import entries, events, items, schedules
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def tenant(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        yield brain_db


def test_what_happened_to_an_item_in_order(tenant):
    iid = items.add("shopping", "رمان")
    items.update(iid, done=True)
    items.update(iid, done=False)
    items.update(iid, text="رمان أحمر")
    items.delete(iid)
    log = events.since(0)
    assert [e["op"] for e in log] == ["added", "done", "reopened", "edited", "removed"]
    assert [e["seq"] for e in log] == [1, 2, 3, 4, 5] and events.last_seq() == 5
    assert log[0]["after"]["text"] == "رمان" and log[0]["list"] == "shopping"
    assert log[3]["before"] == {"text": "رمان"} and log[3]["after"] == {"text": "رمان أحمر"}
    assert log[4]["before"]["text"] == "رمان أحمر" and log[4]["after"] is None
    assert all(e["row"] == iid and e["coll"] == "sandy_items" for e in log)


def test_entries_and_schedules_are_logged_too(tenant):
    entries.add("expense", "غدا", {"amount": 40})
    schedules.add("reminder", "الدوا", datetime.now(timezone.utc) + timedelta(hours=1))
    assert [(e["coll"], e["op"], e["kind"]) for e in events.since(0)] == [
        ("sandy_entries", "added", "expense"), ("sandy_schedules", "added", "reminder")]


def test_an_edit_that_changes_nothing_is_no_event(tenant):
    iid = items.add("shopping", "رمان")
    items.update(iid, text="رمان")
    assert len(events.since(0)) == 1


def test_each_account_has_its_own_log(brain_db):  # noqa: F811
    with active_user_profile_context(A):
        items.add("shopping", "رمان")
        items.add("shopping", "بطيخ")
    with active_user_profile_context(B):
        items.add("shopping", "خبز")
        assert [e["after"]["text"] for e in events.since(0)] == ["خبز"] and events.last_seq() == 1
    with active_user_profile_context(A):
        assert events.last_seq() == 2


def test_sealed_words_stay_sealed(tenant):
    from app.utils.ltm_crypto import encrypt_field
    sealed = encrypt_field("سري")
    entries.add("fact", sealed, {"encrypted": sealed != "سري"}, embed=False)
    assert events.since(0)[0]["after"]["text"] == sealed


def test_a_copied_in_row_is_no_event(tenant):
    items.add("shopping", "قديم", migrated_from={"collection": "old", "id": "1"})
    assert events.since(0) == []


def test_it_lives_ninety_days(tenant):
    items.add("shopping", "رمان")
    e = events.since(0)[0]
    assert events.KEEP_DAYS == 90 and e["expire_at"] - e["at"] == timedelta(days=90)
    ttl = [i for i in tenant[events.EVENTS].index_information().values()
           if i.get("expireAfterSeconds") == 0]
    assert ttl and ttl[0]["key"] == [("expire_at", 1)]
