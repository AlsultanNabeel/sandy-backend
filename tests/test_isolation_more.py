"""More cross-tenant isolation — the surfaces added after the core suite.

Complements test_tenant_isolation.py by covering the home-control device store
(the original leak bug class), the per-user daily-nudge answers + persona in the
accounts store, and the push-token address book. Same guarantees: a user never
sees or mutates another user's data, and unauthenticated writes go nowhere.
"""

from __future__ import annotations

import os

import mongomock
import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-for-isolation-more")

from app.utils.user_profiles import active_user_profile_context  # noqa: E402


def as_tenant(tenant_id):
    return active_user_profile_context(
        {"chat_id": tenant_id, "permissions": "all", "relation": "user"}
    )


def no_tenant():
    return active_user_profile_context(None)


@pytest.fixture
def db():
    from app.features import device_store, push_tokens_store, users_store
    database = mongomock.MongoClient().db
    device_store.init_device_store(database)
    push_tokens_store.init_push_tokens_store(database)
    users_store.init_users_store(database)
    return database


# ── home-control devices (the room-control leak class) ──────────────────────

def _add_device(name):
    from app.features import device_store
    return device_store.add_device(
        name=name, label=name, control_type="switch",
        transport={"kind": "mqtt", "topic": f"room/cmd/{name}"},
    )


def test_devices_isolated(db):
    from app.features import device_store

    with as_tenant("tenant-A"):
        _add_device("lamp_a")
    with as_tenant("tenant-B"):
        _add_device("lamp_b")

    with as_tenant("tenant-A"):
        names_a = {d.get("name") for d in device_store.list_devices()}
        # B's device is invisible AND unreadable by id from A's context.
        assert device_store.get_device("lamp_b") is None
    with as_tenant("tenant-B"):
        names_b = {d.get("name") for d in device_store.list_devices()}

    assert names_a == {"lamp_a"}, f"LEAK/loss in A: {names_a}"
    assert names_b == {"lamp_b"}, f"LEAK/loss in B: {names_b}"


def test_device_cannot_be_deleted_across_tenants(db):
    from app.features import device_store

    with as_tenant("tenant-A"):
        _add_device("lamp_a")
    # B tries to delete A's device by name — must not affect A's data.
    with as_tenant("tenant-B"):
        device_store.delete_device("lamp_a")
    with as_tenant("tenant-A"):
        assert device_store.get_device("lamp_a") is not None, "B deleted A's device!"


def test_devices_fail_closed_without_tenant(db):
    from app.features import device_store

    with no_tenant():
        _add_device("ghost_lamp")
        assert device_store.list_devices() == []
    with as_tenant("tenant-A"):
        assert device_store.get_device("ghost_lamp") is None


# ── daily-nudge answers + persona (per-user account store) ──────────────────

def _mk_user(email):
    from app.features import users_store
    users_store.create_email_user(email, "hash")
    return users_store.get_email_user(email)["_id"]


def test_nudge_answers_isolated(db):
    from app.features import users_store
    uid_a = _mk_user("a@x.com")
    uid_b = _mk_user("b@x.com")

    users_store.record_nudge_answer(uid_a, "unwind", "قراءة")
    users_store.record_nudge_answer(uid_b, "unwind", "رياضة")

    assert users_store.get_nudge_answers(uid_a) == {"unwind": "قراءة"}
    assert users_store.get_nudge_answers(uid_b) == {"unwind": "رياضة"}


def test_persona_isolated(db):
    from app.features import users_store
    uid_a = _mk_user("pa@x.com")
    uid_b = _mk_user("pb@x.com")

    users_store.set_persona(uid_a, dialect="egyptian")
    users_store.set_persona(uid_b, dialect="lebanese")

    assert users_store.get_persona(uid_a)["dialect"] == "egyptian"
    assert users_store.get_persona(uid_b)["dialect"] == "lebanese"


# ── push tokens (device address book) ───────────────────────────────────────

def test_push_tokens_scoped_to_user(db):
    from app.features import push_tokens_store
    push_tokens_store.register_token("tenant-A", "tokA1")
    push_tokens_store.register_token("tenant-A", "tokA2")
    push_tokens_store.register_token("tenant-B", "tokB1")

    assert set(push_tokens_store.tokens_for_user("tenant-A")) == {"tokA1", "tokA2"}
    assert push_tokens_store.tokens_for_user("tenant-B") == ["tokB1"]
    assert set(push_tokens_store.user_ids_with_tokens()) == {"tenant-A", "tenant-B"}
