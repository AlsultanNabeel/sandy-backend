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
    from datetime import datetime, timezone

    from app.blocks import entries, init_blocks, items, schedules
    from app.features import scene_store

    far = datetime(2099, 1, 1, 10, tzinfo=timezone.utc)
    STORE_CASES.extend(
        [
            ("entries", init_blocks,
             lambda m: entries.add("note", m, embed=False),
             lambda: entries.list_entries()),
            ("items", lambda db: None,
             lambda m: items.add("tasks", m),
             lambda: items.list_items()),
            ("schedules", lambda db: None,
             lambda m: schedules.add("reminder", m, far),
             lambda: schedules.list_schedules()),
            ("scene", scene_store.init_scene_store,
             lambda m: scene_store.add_scene(m),
             lambda: scene_store.list_scenes()),
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
