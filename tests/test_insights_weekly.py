"""GET /api/insights/weekly — numbers, tenant isolation, cached sentence, fallback."""
from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from flask import Flask

from app import db as appdb
from app.agent.facade import agent as facade


def _seed(d, uid, now):
    """This week / last week rows for `uid`, plus noise outside both windows."""
    cur = now - timedelta(days=2)
    prev = now - timedelta(days=9)
    old = now - timedelta(days=30)
    d.sandy_tasks.insert_many([
        {"_id": f"{uid}t1", "user_id": uid, "done": True, "completed_at": cur},
        {"_id": f"{uid}t2", "user_id": uid, "done": True, "completed_at": cur},
        {"_id": f"{uid}t3", "user_id": uid, "done": True, "completed_at": prev},
        {"_id": f"{uid}t4", "user_id": uid, "done": True, "completed_at": old},
        {"_id": f"{uid}t5", "user_id": uid, "done": False, "completed_at": None},
    ])
    d.sandy_reminders.insert_many([
        {"_id": f"{uid}r1", "user_id": uid, "remind_at": cur},
        {"_id": f"{uid}r2", "user_id": uid, "remind_at": now + timedelta(days=1)},
    ])
    d.sandy_focus.insert_many([
        {"_id": f"{uid}f1", "user_id": uid, "state": "done", "ended_at": cur, "focused_min": 25},
        {"_id": f"{uid}f2", "user_id": uid, "state": "cancelled", "ended_at": cur, "focused_min": 10},
        {"_id": f"{uid}f3", "user_id": uid, "state": "done", "ended_at": prev, "focused_min": 50},
    ])
    d.sandy_expenses.insert_many([
        {"_id": f"{uid}e1", "user_id": uid, "at": cur, "amount": 10.5},
        {"_id": f"{uid}e2", "user_id": uid, "at": cur, "amount": 4.5},
        {"_id": f"{uid}e3", "user_id": uid, "at": prev, "amount": 100},
    ])
    d.sandy_journal.insert_one({"_id": f"{uid}j1", "user_id": uid, "at": prev, "date": "x"})
    d.sandy_reading_sessions.insert_many([
        {"_id": f"{uid}s1", "user_id": uid, "state": "done", "ended_at": cur,
         "start_page": 10, "end_page": 30},
        {"_id": f"{uid}s2", "user_id": uid, "state": "active", "ended_at": None},
    ])
    from app.utils.time import USER_TZ
    today = now.astimezone(USER_TZ).date()
    d.sandy_habits.insert_one({"_id": f"{uid}h", "user_id": uid, "name": "walk",
                               "created_at": now})
    d.sandy_habit_log.insert_many([
        {"_id": f"{uid}l{i}", "user_id": uid, "habit_id": f"{uid}h",
         "date": (today - timedelta(days=i)).isoformat()}
        for i in (0, 1, 2, 8)
    ])
    ts = lambda dt: dt.isoformat()  # noqa: E731
    d.sandy_stm.insert_one({
        "key": f"app:{uid}", "user_id": uid, "updated_at": now,
        "history": [
            {"role": "user", "content": "hi", "timestamp": ts(cur)},
            {"role": "assistant", "content": "hey", "timestamp": ts(cur)},
            {"role": "user", "content": "yo", "timestamp": ts(cur)},
            {"role": "user", "content": "old", "timestamp": ts(prev)},
        ],
    })


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    d = mongomock.MongoClient().db
    appdb.configure(d)
    from app.api.insights_api import register_insights_api
    app = Flask(__name__)
    register_insights_api(app, mongo_db=d)
    now = datetime.now(timezone.utc)
    _seed(d, "u1", now)
    _seed(d, "u2", now)
    d.sandy_tasks.insert_one({"_id": "u2extra", "user_id": "u2", "done": True,
                              "completed_at": now - timedelta(hours=1)})
    yield d, app.test_client()
    appdb.reset()


def _get(client, uid, role="user", lang="ar"):
    from app.api.auth_handlers import make_token
    h = {"Authorization": f"Bearer {make_token(role, user_id=uid)}"}
    return client.get(f"/api/insights/weekly?lang={lang}", headers=h)


def _metrics(body):
    return {m["key"]: (m["current"], m["previous"]) for m in body["metrics"]}


def test_numbers_on_seeded_data(env, monkeypatch):
    _, client = env
    monkeypatch.setattr(facade, "create_chat_completion", lambda **k: "أسبوع حلو!")
    r = _get(client, "u1")
    assert r.status_code == 200
    body = r.get_json()
    m = _metrics(body)
    assert m["tasks_completed"] == (2, 1)
    assert m["reminders_done"] == (1, 0)
    assert m["focus_minutes"] == (35, 50)
    assert m["expenses_total"] == (15.0, 100.0)
    assert m["journal_entries"] == (0, 1)
    assert m["reading_pages"] == (20, 0)
    assert m["reading_sessions"] == (1, 0)
    assert m["habit_checkins"] == (3, 1)
    assert m["chat_turns"] == (2, 1)
    assert body["best_streak"] == 3
    assert body["demo"] is False
    assert body["sentence"] == "أسبوع حلو!" and body["sentence_source"] == "llm"


def test_tenant_isolation(env, monkeypatch):
    _, client = env
    monkeypatch.setattr(facade, "create_chat_completion", lambda **k: "ok")
    assert _metrics(_get(client, "u1").get_json())["tasks_completed"] == (2, 1)
    assert _metrics(_get(client, "u2").get_json())["tasks_completed"] == (3, 1)
    assert _metrics(_get(client, "nobody").get_json())["tasks_completed"] == (0, 0)


def test_sentence_generated_once_per_week(env, monkeypatch):
    d, client = env
    calls = []

    def fake(**kw):
        calls.append(kw)
        assert kw.get("timeout")  # the model call is always bounded
        return f"جملة {len(calls)}"

    monkeypatch.setattr(facade, "create_chat_completion", fake)
    first = _get(client, "u1").get_json()["sentence"]
    second = _get(client, "u1").get_json()["sentence"]
    assert first == second == "جملة 1" and len(calls) == 1
    # Cached in the tenant-scoped collection, under this user only.
    docs = list(d.sandy_weekly_insights.find({}))
    assert len(docs) == 1 and docs[0]["user_id"] == "u1"
    # Another user gets their own sentence.
    assert _get(client, "u2").get_json()["sentence"] == "جملة 2"


def test_fallback_when_model_fails(env, monkeypatch):
    _, client = env

    def boom(**kw):
        raise RuntimeError("model down")

    monkeypatch.setattr(facade, "create_chat_completion", boom)
    body = _get(client, "u1").get_json()
    assert body["sentence_source"] == "template" and body["sentence"]
    en = _get(client, "u1", lang="en").get_json()
    assert en["sentence_source"] == "template" and "task" in en["sentence"].lower()
    # Once the model is back, the fallback does not stick for the whole week.
    import app.features.insights as ins
    monkeypatch.setattr(ins, "_FALLBACK_TTL", timedelta(seconds=0))
    monkeypatch.setattr(facade, "create_chat_completion", lambda **k: "رجعت")
    assert _get(client, "u1").get_json()["sentence"] == "رجعت"


def test_model_timeout_falls_back(env, monkeypatch):
    _, client = env
    import time

    import app.features.insights as ins
    monkeypatch.setattr(ins, "_LLM_WAIT_S", 0.05)
    monkeypatch.setattr(facade, "create_chat_completion",
                        lambda **k: time.sleep(0.5) or "late")
    body = _get(client, "u1").get_json()
    assert body["sentence_source"] == "template"


def test_guest_gets_demo_and_anon_is_rejected(env):
    _, client = env
    r = _get(client, None, role="guest")
    assert r.status_code == 200 and r.get_json()["demo"] is True
    assert client.get("/api/insights/weekly").status_code == 401
