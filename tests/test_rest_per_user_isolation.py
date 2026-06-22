"""REST tab endpoints must serve each signed-in user only their OWN data.

Proves the per-user wiring in productivity_api / life_api: two different
``user_id``s hit the same /api/tasks endpoint and each sees only the tasks they
created — never the other user's — using a mongomock-backed webhook app.
"""

import os

import mongomock
import pytest

# These must be set before auth_handlers / user_profiles read them at import.
os.environ.setdefault("JWT_SECRET", "test-secret-for-isolation")
os.environ.setdefault("OWNER_CHAT_ID", "999000")


class _FakeTelegramBot:
    """Minimal telebot stand-in: only what create_telegram_webhook_app touches."""

    def get_me(self):
        from types import SimpleNamespace

        return SimpleNamespace(id=1, username="sandy_bot")

    def process_new_updates(self, updates):
        pass

    def callback_query_handler(self, func):
        def decorator(f):
            return f

        return decorator


@pytest.fixture
def app_and_db():
    from app.api.webhook import create_telegram_webhook_app
    from app.features import tasks_store

    db = mongomock.MongoClient().db
    # The store reads/writes the collection passed by the API handlers, but
    # init keeps the same handle for any default-path call.
    tasks_store.init_tasks_store(db)

    app = create_telegram_webhook_app(
        telegram_bot=_FakeTelegramBot(),
        webhook_path="/webhook/test",
        mongo_db=db,
    )
    app.testing = True
    return app, db


def _user_token(user_id):
    from app.api.auth_handlers import make_token

    # Regular signed-in app user (not owner): role "user", own stable user_id.
    return make_token("user", user_id=user_id)


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_two_users_see_only_their_own_tasks(app_and_db):
    app, _db = app_and_db
    client = app.test_client()

    tok_a = _user_token("user-A")
    tok_b = _user_token("user-B")

    # Each user creates their own task.
    r = client.post("/api/tasks", json={"text": "مهمة أحمد"}, headers=_auth(tok_a))
    assert r.status_code == 200, r.get_json()
    r = client.post("/api/tasks", json={"text": "مهمة بشير"}, headers=_auth(tok_b))
    assert r.status_code == 200, r.get_json()

    # User A sees only their task.
    ra = client.get("/api/tasks", headers=_auth(tok_a)).get_json()
    texts_a = [t["text"] for t in ra["items"]]
    assert ra["demo"] is False
    assert texts_a == ["مهمة أحمد"]
    assert "مهمة بشير" not in texts_a  # isolation: B's data never leaks to A

    # User B sees only their task.
    rb = client.get("/api/tasks", headers=_auth(tok_b)).get_json()
    texts_b = [t["text"] for t in rb["items"]]
    assert rb["demo"] is False
    assert texts_b == ["مهمة بشير"]
    assert "مهمة أحمد" not in texts_b  # isolation: A's data never leaks to B


def test_task_round_trips_note_and_priority(app_and_db):
    app, _db = app_and_db
    client = app.test_client()
    tok = _user_token("user-C")

    # Create a task carrying the new optional detail fields.
    r = client.post(
        "/api/tasks",
        json={"text": "اجتماع", "note": "أحضر الشرائح", "priority": "high"},
        headers=_auth(tok),
    )
    assert r.status_code == 200, r.get_json()

    # GET payload echoes note + priority alongside the existing keys.
    item = next(t for t in client.get("/api/tasks", headers=_auth(tok)).get_json()["items"])
    assert item["text"] == "اجتماع"
    assert item["note"] == "أحضر الشرائح"
    assert item["priority"] == "high"
    # Existing keys are untouched.
    assert set(item) >= {"id", "text", "done", "due_at"}

    # An invalid priority falls back to "normal", and the default is "normal".
    r = client.post("/api/tasks", json={"text": "بلا أولوية", "priority": "urgent"}, headers=_auth(tok))
    assert r.status_code == 200
    items = client.get("/api/tasks", headers=_auth(tok)).get_json()["items"]
    fallback = next(t for t in items if t["text"] == "بلا أولوية")
    assert fallback["priority"] == "normal"
    assert fallback["note"] == ""


def test_guest_gets_demo_and_cannot_write(app_and_db):
    app, _db = app_and_db
    from app.api.auth_handlers import make_token

    client = app.test_client()
    guest_tok = make_token("guest")

    # Guests still get the demo tab, never real data.
    rg = client.get("/api/tasks", headers=_auth(guest_tok)).get_json()
    assert rg["demo"] is True

    # Guests cannot create tasks.
    rw = client.post("/api/tasks", json={"text": "x"}, headers=_auth(guest_tok))
    assert rw.status_code == 403


def test_unauthenticated_is_rejected(app_and_db):
    app, _db = app_and_db
    client = app.test_client()
    assert client.get("/api/tasks").status_code == 401
    assert client.post("/api/tasks", json={"text": "x"}).status_code == 401
