"""Cross-tenant isolation — the structural guard for the whole feature surface.

Every feature store must obey the same contract, by architecture not by luck:

  1. **Isolation** — data written under tenant A is never visible to tenant B,
     and B can't mutate A's rows by id.
  2. **Fail-closed** — with no authenticated tenant in context, reads return
     nothing and writes go nowhere (no shared/global bucket).

This runs every store through that contract over a mongomock database. It is the
regression net for the tenant-scoped data layer (``app.utils.tenant_db``): if a
future query forgets to scope, one of these assertions fails in CI instead of
leaking a user's data in production (the room-control bug class).

The stores are exercised through their PUBLIC API only — the same calls the web
API and the agent make — so this proves the real path, not an internal shortcut.
"""

from __future__ import annotations

import os

import mongomock
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-isolation")

from app.utils.user_profiles import active_user_profile_context  # noqa: E402

FAR_FUTURE = "2099-01-01T10:00:00"


def as_tenant(tenant_id):
    """Run a block as an authenticated user with full permissions on their own
    tenant — exactly what build_user_profile produces for a signed-in user."""
    return active_user_profile_context(
        {"chat_id": tenant_id, "permissions": "all", "relation": "user"}
    )


def no_tenant():
    """Run a block with no authenticated user (the fail-closed condition)."""
    return active_user_profile_context(None)


def _blob(items) -> str:
    """Everything a tenant can see, stringified — robust to each store's key
    names. We only assert on whether a unique marker appears in it."""
    return repr(list(items or []))


# (name, init(db), create(marker) under active tenant, list() under active tenant)
STORE_CASES = []


def _register():
    from app.features import (
        expenses_store,
        habits_store,
        journal_store,
        reading_store,
        reminders_store,
        scene_store,
        shopping_store,
        tasks_store,
    )

    STORE_CASES.extend(
        [
            (
                "tasks",
                tasks_store.init_tasks_store,
                lambda m: tasks_store.add_task(m),
                lambda: tasks_store.load_tasks(),
            ),
            (
                "shopping",
                shopping_store.init_shopping_store,
                lambda m: shopping_store.add_item(m),
                lambda: shopping_store.list_items(include_bought=True),
            ),
            (
                "reminders",
                reminders_store.init_reminders_store,
                lambda m: reminders_store.add_reminder(m, FAR_FUTURE),
                lambda: reminders_store.load_reminders(),
            ),
            (
                "habits",
                habits_store.init_habits_store,
                lambda m: habits_store.add_habit(m),
                lambda: habits_store.list_habits(),
            ),
            (
                "journal",
                journal_store.init_journal_store,
                lambda m: journal_store.add_entry(m),
                lambda: journal_store.recent_entries(),
            ),
            (
                "expenses",
                expenses_store.init_expenses_store,
                lambda m: expenses_store.add_expense(1.0, note=m),
                lambda: expenses_store.list_expenses(),
            ),
            (
                "reading",
                reading_store.init_reading_store,
                lambda m: reading_store.add_book(m),
                lambda: reading_store.list_books(),
            ),
            (
                "scene",
                scene_store.init_scene_store,
                lambda m: scene_store.add_scene(m),
                lambda: scene_store.list_scenes(),
            ),
        ]
    )


_register()


@pytest.fixture
def db():
    database = mongomock.MongoClient().db
    for _name, init, _create, _list in STORE_CASES:
        init(database)
    return database


@pytest.mark.parametrize("name,init,create,list_", STORE_CASES, ids=[c[0] for c in STORE_CASES])
def test_store_isolates_tenants(db, name, init, create, list_):
    # Lowercase markers: some stores (e.g. scenes) normalise names to lowercase.
    mark_a = f"mark-{name}-aaa-zzz"
    mark_b = f"mark-{name}-bbb-zzz"

    with as_tenant("tenant-A"):
        create(mark_a)
    with as_tenant("tenant-B"):
        create(mark_b)

    # A sees only A; B sees only B.
    with as_tenant("tenant-A"):
        blob_a = _blob(list_())
    with as_tenant("tenant-B"):
        blob_b = _blob(list_())

    assert mark_a in blob_a, f"{name}: tenant A can't see its own data"
    assert mark_b not in blob_a, f"{name}: LEAK — tenant B's data visible to A"
    assert mark_b in blob_b, f"{name}: tenant B can't see its own data"
    assert mark_a not in blob_b, f"{name}: LEAK — tenant A's data visible to B"


@pytest.mark.parametrize("name,init,create,list_", STORE_CASES, ids=[c[0] for c in STORE_CASES])
def test_store_fails_closed_without_tenant(db, name, init, create, list_):
    mark = f"mark-{name}-notenant-zzz"

    # A write with no authenticated tenant must go nowhere — not into a shared
    # bucket, not under some default id.
    with no_tenant():
        create(mark)
        blob_none = _blob(list_())

    assert mark not in blob_none, f"{name}: read returned data with no tenant"

    # And no real tenant inherits the unscoped write.
    with as_tenant("tenant-A"):
        blob_a = _blob(list_())
    assert mark not in blob_a, f"{name}: no-tenant write leaked into a real tenant"


def test_conversation_summary_search_reads_only_the_callers_summaries(db, monkeypatch):
    """Summaries carry the client-chosen thread id; two accounts that both used
    "default" must never find each other's."""
    from app.api.conversations_api import _semantic_hits
    from app.blocks import entries

    monkeypatch.setattr(entries, "embed_text", lambda text: None)
    for uid, text in (("userA", "حكينا عن السفر لإيطاليا"), ("userB", "السفر لتركيا بالصيف")):
        with active_user_profile_context({"chat_id": uid}):
            entries.add("summary", text, {"thread_id": "default"}, embed=False)
    hits = _semantic_hits("userA", "السفر")
    assert hits == [("default", "حكينا عن السفر لإيطاليا")]
    assert _semantic_hits("", "السفر") == []
