"""scripts/migrate_to_blocks.py: dry run writes nothing, apply writes, re-apply is a no-op."""
from datetime import datetime, timedelta

import mongomock
import pytest

from app import db as appdb
from scripts import migrate_to_blocks as mig

_T = datetime(2026, 9, 1, 9, 0)  # Mongo hands back naive UTC


def _seed(d, uid):
    u = {"user_id": uid}
    c = {"chat_id": uid}
    d.sandy_tasks.insert_many([
        {**u, "_id": f"{uid}-t1", "text": "task one", "notes": "", "done": False,
         "created_at": _T, "completed_at": None, "due_date": "2026-09-10",
         "due_at": _T + timedelta(days=9), "priority": "high", "project": ""},
        {**u, "_id": f"{uid}-t2", "text": "task two", "notes": "n", "done": True,
         "created_at": _T, "completed_at": _T, "due_date": "", "due_at": None,
         "priority": "", "project": "home"},
    ])
    d.sandy_shopping.insert_one({**u, "_id": f"{uid}-s1", "text": "milk", "category": "",
                                 "done": False, "price": 0.0, "qty": 1, "unit": "",
                                 "created_at": _T, "bought_at": None})
    d.sandy_goals.insert_one({**c, "user_id": uid, "text": "run 5k", "deadline": "2026-12-01",
                              "status": "active", "created_at": _T, "updated_at": _T})
    d.sandy_books.insert_one({**u, "_id": f"{uid}-b1", "title": "Dune", "author": "Herbert",
                              "category": "", "cover_url": "", "total_pages": 400,
                              "current_page": 50, "rating": 0, "fmt": "paper",
                              "status": "reading", "notes": [{"text": "n", "at": _T}],
                              "quotes": [], "started_at": _T, "created_at": _T,
                              "finished_at": None})
    d.sandy_habits.insert_one({**u, "_id": f"{uid}-h1", "name": "walk",
                               "created_at": _T, "archived": False})
    d.sandy_brainstorms.insert_many([
        {**c, "topic": "app idea", "status": "done", "points": [{"text": "p", "at": "x"}],
         "plan_text": "plan", "summary": "s", "started_at": _T.isoformat(), "finished_at": ""},
        {**c, "topic": "dropped", "status": "abandoned", "points": [], "plan_text": "",
         "started_at": _T.isoformat(), "finished_at": ""},
    ])
    d.sandy_habit_log.insert_one({**u, "_id": f"{uid}-h1:2026-09-01",
                                  "habit_id": f"{uid}-h1", "date": "2026-09-01"})
    d.sandy_expenses.insert_one({**u, "_id": f"{uid}-e1", "amount": 12, "note": "lunch",
                                 "category": "food", "at": _T})
    d.sandy_journal.insert_one({**u, "_id": f"{uid}-j1", "date": "2026-09-01",
                                "text": "good day", "at": _T})
    d.sandy_reading_sessions.insert_one({**u, "_id": f"{uid}-r1", "book_id": f"{uid}-b1",
                                         "started_at": _T, "ended_at": _T + timedelta(hours=1),
                                         "paused_at": None, "paused_total_sec": 0,
                                         "start_page": 10, "end_page": 50, "state": "done"})
    d.sandy_memories.insert_many([
        {**c, "label": "user_fact", "category": "food", "content": "likes tea", "created_at": _T},
        {**c, "label": "عائلة", "content": "has two brothers", "created_at": _T},
        {**c, "user_id": uid, "label": "emotional_memory", "mood": "happy",
         "topic": "enc:abc", "created_at": _T},
        {**c, "user_id": uid, "label": "style_memory", "preference": "short replies",
         "source_message": "be brief", "created_at": _T},
        {**c, "user_id": uid, "label": "lesson_learned", "lesson": "no emojis", "created_at": _T},
        {**c, "user_id": uid, "label": "relationship", "relation": "sister", "name": "Mona",
         "created_at": _T},
        {**c, "user_id": uid, "label": "interest", "keyword": "chess", "count": 3,
         "last_seen": _T, "created_at": _T},
        {**c, "user_id": uid, "label": "milestone", "signal": "new_job", "context": "enc:x",
         "event_date": "2026-01-02", "created_at": _T},
        {**c, "user_id": uid, "thread_id": "t", "label": "conversation_summary",
         "summary": "we talked", "source_turns": 20, "created_at": _T, "embedding": [0.1, 0.2]},
    ])
    d.sandy_photos.insert_one({**c, "name": "beach", "grid_id": "g1", "file_unique_id": "f1",
                               "user_caption": "", "ai_caption": "sea", "tags": ["sea"],
                               "created_at": _T.isoformat()})
    d.sandy_reminders.insert_one({**u, "_id": f"{uid}-rem1", "text": "pills",
                                  "remind_at": _T + timedelta(days=1), "recurrence": "FREQ=DAILY",
                                  "kind": "reminder", "parent_summary": "", "note": "",
                                  "linked_task_id": "", "send_state": "sending",
                                  "created_at": _T, "sent_at": None, "last_error": ""})
    d.sandy_future_messages.insert_one({**c, "user_id": uid, "text": "enc:hi future",
                                        "deliver_at": _T + timedelta(days=30),
                                        "delivered": False, "created_at": _T})
    d.sandy_scene_timers.insert_one({**u, "fire_at": _T + timedelta(minutes=5),
                                     "device": "light", "value": "off"})
    d.sandy_daily_nudge.insert_one({**u, "_id": f"{uid}:2026-09-01",
                                    "nudge": {"kind": "agenda", "text": "busy day"},
                                    "created_at": _T})


# One per source row above, and what each lands as.
_PER_TENANT = {
    "sandy_items:tasks": 2, "sandy_items:shopping": 1, "sandy_items:goals": 1,
    "sandy_items:reading": 1, "sandy_items:habits": 1, "sandy_items:plans": 1,
    "sandy_entries:habit": 1, "sandy_entries:expense": 1, "sandy_entries:journal": 1,
    "sandy_entries:reading": 1, "sandy_entries:fact": 7, "sandy_entries:mood": 1,
    "sandy_entries:summary": 1, "sandy_entries:photo": 1,
    "sandy_schedules:reminder": 1, "sandy_schedules:message_to_future_self": 1,
    "sandy_schedules:scene": 1, "sandy_schedules:daily_nudge": 1,
}
_TOTAL = sum(_PER_TENANT.values())
_TARGETS = ("sandy_entries", "sandy_items", "sandy_schedules")


@pytest.fixture
def db():
    d = mongomock.MongoClient().db
    appdb.configure(d)
    _seed(d, "u1")
    _seed(d, "u2")
    yield d
    appdb.reset()


def _snapshot(d):
    return {n: sorted(map(repr, d[n].find())) for n in d.list_collection_names()
            if n not in _TARGETS}


def _count(d):
    return sum(d[n].count_documents({}) for n in _TARGETS)


def test_every_source_has_a_seeded_doc():
    seeded = {s.collection for s in mig.SOURCES}
    d = mongomock.MongoClient().db
    _seed(d, "u")
    assert seeded <= set(d.list_collection_names())


def test_dry_run_writes_nothing_and_counts_everything(db):
    before = _snapshot(db)
    report = mig.run(db)
    assert _count(db) == 0
    assert _snapshot(db) == before
    assert dict(report.targets) == {k: 2 * v for k, v in _PER_TENANT.items()}
    assert sum(report.invalid.values()) == 0, report.errors
    assert all(1 <= len(v) <= 3 for v in report.samples.values())


def test_apply_writes_the_right_counts_and_shapes(db):
    before = _snapshot(db)
    report = mig.run(db, apply=True)
    assert _count(db) == 2 * _TOTAL == sum(report.written.values())
    assert _snapshot(db) == before  # old collections untouched

    for key, n in _PER_TENANT.items():
        coll, name = key.split(":")
        field = "list" if coll == "sandy_items" else "kind"
        assert db[coll].count_documents({"user_id": "u1", field: name}) == n, key
    for coll in _TARGETS:
        assert db[coll].count_documents({"migrated_from": None}) == 0

    items = db.sandy_items
    task = items.find_one({"migrated_from.id": "u1-t1"})
    assert task["user_id"] == "u1" and task["priority"] == "high" and task["due"] is not None
    assert items.find_one({"migrated_from.id": "u1-t2"})["done"] is True
    habit = items.find_one({"migrated_from.id": "u1-h1"})
    check_in = db.sandy_entries.find_one({"kind": "habit", "user_id": "u1"})
    assert check_in["data"]["habit_item_id"] == habit["_id"] and check_in["text"] == "walk"
    session = db.sandy_entries.find_one({"kind": "reading", "user_id": "u1"})
    assert session["data"]["pages"] == 40 and session["text"] == "Dune"
    assert session["data"]["book_item_id"] == items.find_one({"migrated_from.id": "u1-b1"})["_id"]
    summary = db.sandy_entries.find_one({"kind": "summary", "user_id": "u1"})
    assert summary["embedding"] == [0.1, 0.2]
    mood = db.sandy_entries.find_one({"kind": "mood", "user_id": "u1"})
    assert mood["text"] == "enc:abc" and mood["data"]["encrypted"] is True
    rem = db.sandy_schedules.find_one({"kind": "reminder", "user_id": "u1"})
    assert rem["status"] == "pending" and rem["recurrence"] == "FREQ=DAILY"


def test_second_apply_writes_nothing(db):
    mig.run(db, apply=True)
    after_first = _count(db)
    report = mig.run(db, apply=True)
    assert _count(db) == after_first
    assert sum(report.written.values()) == 0
    assert sum(report.already.values()) == 2 * _TOTAL


def test_user_flag_limits_to_one_tenant(db):
    mig.run(db, apply=True, user="u2")
    assert _count(db) == _TOTAL
    for coll in _TARGETS:
        assert db[coll].count_documents({"user_id": {"$ne": "u2"}}) == 0


def test_a_doc_that_does_not_fit_is_reported_not_written(db):
    db.sandy_expenses.insert_one({"user_id": "u1", "_id": "bad", "amount": "twelve",
                                  "at": _T})
    db.sandy_reminders.insert_one({"user_id": "u1", "_id": "no-time", "text": "x"})
    report = mig.run(db, apply=True)
    assert report.invalid["sandy_expenses"] == 1 and report.invalid["sandy_reminders"] == 1
    assert db.sandy_entries.find_one({"migrated_from.id": "bad"}) is None
    assert db.sandy_schedules.find_one({"migrated_from.id": "no-time"}) is None


def test_print_report_runs(db, capsys):
    mig.print_report(mig.run(db), apply=False)
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "sandy_tasks" in out and "Samples" in out
