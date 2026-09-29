"""CRUD, filters and tenant isolation for the three blocks."""
from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from app import db as appdb
from app.blocks import entries, init_blocks, items, schedules
from app.blocks.kinds import KindError
from app.utils.user_profiles import active_user_profile_context

_A = {"chat_id": "userA", "relation": "user", "permissions": "all"}
_B = {"chat_id": "userB", "relation": "user", "permissions": "all"}
_NOW = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


@pytest.fixture
def db(monkeypatch):
    d = mongomock.MongoClient().db
    appdb.configure(d)
    init_blocks(d)
    monkeypatch.setattr(entries, "embed_text", lambda text: None)
    yield d
    appdb.reset()


def test_entries_crud_and_filters(db):
    with active_user_profile_context(_A):
        e1 = entries.add("expense", "قهوة", {"amount": 3.5, "category": "food"},
                         at=_NOW - timedelta(days=2), source="chat")
        e2 = entries.add("journal", "يوم طويل", {"date": "2026-09-01"}, at=_NOW)
        assert entries.get(e1)["data"]["amount"] == 3.5
        assert entries.get(e1)["kind"] == "expense"
        assert "user_id" not in entries.get(e1) and "embedding" not in entries.get(e1)

        assert [e["id"] for e in entries.list_entries()] == [e2, e1]
        assert [e["id"] for e in entries.list_entries("expense")] == [e1]
        assert [e["id"] for e in entries.list_entries(since=_NOW - timedelta(days=1))] == [e2]
        assert [e["id"] for e in entries.list_entries(until=_NOW - timedelta(days=1))] == [e1]
        assert [e["id"] for e in entries.list_entries(text="طويل")] == [e2]

        assert entries.update(e1, text="قهوة كبيرة", data={"amount": 5})
        got = entries.get(e1)
        assert got["text"] == "قهوة كبيرة" and got["data"] == {"amount": 5}
        with pytest.raises(KindError):
            entries.update(e1, data={"mood": "happy"})

        assert entries.delete(e1)
        assert entries.get(e1) is None
        assert not entries.delete(e1)
        assert not entries.update(e1, text="x")


def test_entries_refuse_bad_kind_and_source(db):
    with active_user_profile_context(_A):
        with pytest.raises(KindError):
            entries.add("gift", "x")
        with pytest.raises(ValueError):
            entries.add("note", "x", source="telegram")
    assert db["sandy_entries"].count_documents({}) == 0


def test_entries_store_the_embedding_helper_result(db, monkeypatch):
    monkeypatch.setattr(entries, "embed_text", lambda text: [0.1, 0.2])
    with active_user_profile_context(_A):
        eid = entries.add("note", "hello")
        no_vec = entries.add("note", "quiet", embed=False)
    assert db["sandy_entries"].find_one({"_id": eid})["embedding"] == [0.1, 0.2]
    assert db["sandy_entries"].find_one({"_id": no_vec})["embedding"] is None


def test_items_crud_and_filters(db):
    with active_user_profile_context(_A):
        t1 = items.add("tasks", "اتصل بالبنك", {"notes": "قبل الظهر"},
                       due=_NOW + timedelta(days=1), priority="high")
        s1 = items.add("shopping", "حليب", {"qty": 2})
        p1 = items.add("project:kitchen", "اشتري رفوف")
        assert items.get(t1)["priority"] == "high"
        assert [i["id"] for i in items.list_items()] == [t1, s1, p1]
        assert [i["id"] for i in items.list_items("shopping")] == [s1]
        assert [i["id"] for i in items.list_items(due_before=_NOW + timedelta(days=2))] == [t1]
        assert [i["id"] for i in items.list_items(text="حليب")] == [s1]

        assert items.update(s1, done=True)
        assert items.get(s1)["done"] and items.get(s1)["done_at"] is not None
        assert [i["id"] for i in items.list_items(done=False)] == [t1, p1]
        assert [i["id"] for i in items.list_items(done=True)] == [s1]
        assert items.update(s1, done=False)
        assert items.get(s1)["done_at"] is None

        assert items.update(t1, due=None, text="اتصل بالبنك اليوم")
        assert items.get(t1)["due"] is None
        with pytest.raises(KindError):
            items.update(t1, data={"price": 3})

        assert items.delete(p1) and items.get(p1) is None


def test_schedules_crud_and_filters(db):
    with active_user_profile_context(_A):
        r1 = schedules.add("reminder", "دوا", _NOW + timedelta(hours=1),
                           {"note": "بعد الأكل"}, recurrence="FREQ=DAILY")
        r2 = schedules.add("scene", "light → off", _NOW + timedelta(minutes=5),
                           {"device": "light", "value": "off"})
        assert schedules.get(r1)["recurrence"] == "FREQ=DAILY"
        assert [s["id"] for s in schedules.list_schedules()] == [r2, r1]
        assert [s["id"] for s in schedules.list_schedules("reminder")] == [r1]
        assert [s["id"] for s in schedules.list_schedules(
            until=_NOW + timedelta(minutes=30))] == [r2]

        assert schedules.update(r2, status="sent")
        assert [s["id"] for s in schedules.list_schedules(status="pending")] == [r1]
        with pytest.raises(ValueError):
            schedules.update(r1, status="done")
        with pytest.raises(ValueError):
            schedules.add("reminder", "x", "tomorrow")

        assert schedules.delete(r1) and schedules.get(r1) is None


def test_no_tenant_reads_and_writes_nothing(db):
    assert entries.add("note", "x") == ""
    assert items.add("tasks", "x") == ""
    assert schedules.add("reminder", "x", _NOW) == ""
    assert entries.list_entries() == [] and items.list_items() == []
    assert schedules.list_schedules() == []
    assert db["sandy_entries"].count_documents({}) == 0


def test_user_a_cannot_see_or_touch_user_b(db):
    with active_user_profile_context(_B):
        eb = entries.add("note", "B's secret")
        ib = items.add("tasks", "B's task")
        sb = schedules.add("reminder", "B's reminder", _NOW)
    with active_user_profile_context(_A):
        # An explicit user_id in the call cannot widen the scope.
        assert entries.get(eb) is None and items.get(ib) is None and schedules.get(sb) is None
        assert entries.list_entries() == [] and items.list_items() == []
        assert schedules.list_schedules() == []
        assert not entries.update(eb, text="hacked") and not items.update(ib, done=True)
        assert not schedules.update(sb, status="cancelled")
        assert not entries.delete(eb) and not items.delete(ib) and not schedules.delete(sb)
        items.add("tasks", "A's task")
    with active_user_profile_context(_B):
        assert entries.get(eb)["text"] == "B's secret"
        assert [i["text"] for i in items.list_items()] == ["B's task"]
        assert schedules.get(sb)["status"] == "pending"
    assert db["sandy_items"].find_one({"text": "A's task"})["user_id"] == "userA"


def test_indexes_lead_with_the_tenant(db):
    for name in ("sandy_entries", "sandy_items", "sandy_schedules"):
        info = db[name].index_information()
        custom = [v["key"] for k, v in info.items() if k != "_id_"]
        assert custom and all(key[0][0] == "user_id" for key in custom)
