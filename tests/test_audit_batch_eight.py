"""Batch eight — an independent pass, and what it found.

The handover for this audit named areas it had not covered. Two of them held
the worst defects of the whole exercise, and both are about a customer leaving:

* **Unpairing a robot did not stop the app controlling it.** `unpair_node`
  deleted the node row, and nothing else. Every device the node actuates — the
  light, the neck, the face — kept its row, and §2.7's boundary asks *"is this
  topic a device in the calling tenant's registry?"*, not *"does the tenant
  still own the node"*. The board is no help either: its topics come from the
  pairing code compiled into it, so it obeys whoever publishes. Sell the robot,
  and the seller's phone still switches the buyer's light.

* **Deleting an account left nine collections behind**, including the semantic
  facts, the conversation turns, the emotional memory and the photos.
  `_erase` filtered on `user_id` alone while four of those stores key on
  `chat_id` — `scoped(..., field="chat_id")` — and eight more were never in the
  list. The module's own docstring: *"a delete that misses one is worse than no
  delete at all."*

Both were reported by the owner from using the product, and both reproduced on
the first attempt.
"""
from __future__ import annotations

import mongomock
import pytest


U = "cust-1"
P = {"user_id": U, "chat_id": U, "relation": "user", "permissions": "all",
     "is_guest": False}


@pytest.fixture()
def db():
    import app.db as appdb

    database = mongomock.MongoClient()["t"]
    database["sandy_users"].insert_one({"_id": U, "user_id": U})
    appdb.configure(database)
    try:
        yield database
    finally:
        appdb.reset()


def _paired_robot_with_a_light():
    from app.features import device_store, node_store

    result = node_store.pair_node("ABC123", label="روبوتي")
    node_id = result.get("node_id") or node_store.code_to_node_id("ABC123")
    device_store.add_device(
        "light", "نور الغرفة", "switch",
        {"kind": "node", "node_id": node_id, "output": "room/light"})
    topic = device_store.device_topic(device_store.get_device("light"))
    return node_id, topic


def test_unpairing_a_robot_stops_the_app_controlling_it(db):
    """The seller's phone kept the light in its list and kept it switchable."""
    from app.features import device_store, node_store
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(P):
        node_id, topic = _paired_robot_with_a_light()
        assert device_store.tenant_owns_topic(topic), "the fixture is wrong"

        out = node_store.unpair_node(node_id)

        assert out["ok"] is True
        assert out["devices_removed"] == 1, \
            "unpair reported success while leaving the devices behind"
        assert not device_store.tenant_owns_topic(topic), \
            "the account can still actuate a robot it no longer owns"
        assert device_store.list_devices() == [], \
            "the app still lists a device on a released node"


def test_unpairing_one_robot_leaves_another_tenants_devices_alone(db):
    """The new delete is tenant-scoped, so it cannot reach sideways.

    Writing this found the *second* boundary, and it holds on its own:
    `add_device` refuses a `node` transport pointing at a node the caller has
    not paired (`node_not_paired`), so a second tenant cannot even name another
    account's node id. This asserts the delete anyway — one boundary standing on
    another is how a change to either becomes a leak nobody expected.
    """
    from app.features import device_store, node_store
    from app.utils import user_profiles

    other = {**P, "user_id": "cust-2", "chat_id": "cust-2"}
    db["sandy_users"].insert_one({"_id": "cust-2", "user_id": "cust-2"})

    with user_profiles.active_user_profile_context(other):
        refused = device_store.add_device(
            "light", "نور جاري", "switch",
            {"kind": "node", "node_id": "abc123", "output": "room/light"})
        assert refused["error"] == "node_not_paired"
        # A device of their own, on their own transport.
        device_store.add_device("lamp", "لمبتي", "switch",
                                {"kind": "mqtt", "topic": "home/lamp"})

    with user_profiles.active_user_profile_context(P):
        node_id, _ = _paired_robot_with_a_light()
        node_store.unpair_node(node_id)

    with user_profiles.active_user_profile_context(other):
        assert [d["label"] for d in device_store.list_devices()] == ["لمبتي"], \
            "unpairing reached into another account's registry"


def test_deleting_an_account_leaves_nothing_behind(db):
    """Nine collections survived, four of them because they key on `chat_id`
    and the erase only ever filtered on `user_id`."""
    from app.features.account_delete import delete_account

    for coll in ("sandy_facts", "sandy_conversations", "sandy_memories",
                 "sandy_activity", "sandy_context_metadata"):
        db[coll].insert_one({"chat_id": U, "text": "شي"})
    for coll in ("sandy_books", "sandy_photos", "sandy_habit_log", "sandy_gifts",
                 "sandy_reading_sessions", "sandy_reading_meta", "sandy_evals",
                 "sandy_focus_meta", "sandy_bs_pending", "sandy_usage_daily",
                 "sandy_tasks", "sandy_journal"):
        db[coll].insert_one({"user_id": U, "text": "شي"})

    out = delete_account(U)

    assert out["ok"] is True
    left = {c: db[c].count_documents({}) for c in db.list_collection_names()
            if db[c].count_documents({})}
    assert left == {}, f"a full account delete left data behind: {left}"


def test_the_delete_list_covers_every_collection_a_tenant_writes_to(db):
    """**A hand-written list is the thing that goes stale**, and this is the one
    operation nobody can undo to check. Every collection reached through
    `scoped()` anywhere in the app has to be in it."""
    import pathlib
    import re

    root = pathlib.Path(__file__).resolve().parent.parent / "cloud" / "app"
    scoped_colls = set()
    for path in root.rglob("*.py"):
        if "__pycache__" in str(path):
            continue
        src = path.read_text(encoding="utf-8")
        for m in re.finditer(r'scoped\([^,]+,\s*(_COLL|"([a-z_]+)")', src):
            name = m.group(2)
            if not name:
                cm = re.search(r'^_COLL = "([a-z_]+)"', src, re.M)
                name = cm.group(1) if cm else None
            if name:
                scoped_colls.add(name)

    from app.features import account_delete

    covered = set(account_delete._BY_USER) | {account_delete._STM}
    missing = sorted(scoped_colls - covered)
    assert not missing, (
        "these are written through the tenant wrapper and would survive a "
        f"full account delete: {missing}")


def test_deleting_an_account_also_releases_its_robots(db):
    """A node held by a deleted account would be claimed forever, by nobody —
    the hardware becomes unpairable, including by the person holding it."""
    from app.features import device_store, node_store
    from app.features.account_delete import delete_account
    from app.utils import user_profiles

    with user_profiles.active_user_profile_context(P):
        _paired_robot_with_a_light()
    delete_account(U)

    assert db["sandy_nodes"].count_documents({}) == 0
    assert db["sandy_devices"].count_documents({}) == 0
    # And the code can be paired again by whoever buys it.
    other = {**P, "user_id": "cust-2", "chat_id": "cust-2"}
    db["sandy_users"].insert_one({"_id": "cust-2", "user_id": "cust-2"})
    with user_profiles.active_user_profile_context(other):
        assert node_store.pair_node("ABC123", label="روبوت مستعمل")["ok"] is True
        assert device_store is not None
