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
from types import SimpleNamespace

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


def test_memory_tool_isolates_and_fails_closed(db):
    from app.agent.tools.schemas.mcp_tools import memory_recall, memory_store

    ctx = SimpleNamespace(mongo_db=db, state={}, create_chat_completion_fn=None)
    secret_a = "memory-secret-AAA-zzz"
    secret_b = "memory-secret-BBB-zzz"

    with as_tenant("tenant-A"):
        memory_store({"content": secret_a}, ctx)
    with as_tenant("tenant-B"):
        memory_store({"content": secret_b}, ctx)

    with as_tenant("tenant-A"):
        recall_a = memory_recall({"query": secret_b}, ctx)["reply"]
    assert secret_b not in recall_a, "memory: LEAK — B's memory recalled for A"

    # No tenant: write goes nowhere, recall finds nothing.
    with no_tenant():
        memory_store({"content": "ghost-zzz"}, ctx)
    with as_tenant("tenant-A"):
        recall_ghost = memory_recall({"query": "ghost-zzz"}, ctx)["reply"]
    assert "ghost-zzz" not in recall_ghost, "memory: no-tenant write leaked"


def test_focus_goals_isolated_and_fail_closed(db):
    from app.features import focus_store

    focus_store.init_focus_store(db)

    with as_tenant("tenant-A"):
        focus_store.set_focus_goal("day", 11)
    with as_tenant("tenant-B"):
        focus_store.set_focus_goal("day", 22)

    with as_tenant("tenant-A"):
        assert focus_store.get_focus_goals().get("day") == 11
    with as_tenant("tenant-B"):
        assert focus_store.get_focus_goals().get("day") == 22

    with no_tenant():
        # Fail-closed: no write, and the read yields no other tenant's goal.
        focus_store.set_focus_goal("day", 99)
        assert focus_store.get_focus_goals().get("day") != 99
    with as_tenant("tenant-A"):
        assert focus_store.get_focus_goals().get("day") == 11
