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


def test_a_legacy_numeric_id_does_not_survive_the_delete(db):
    """**Mongo equality is type-strict.**

    Legacy documents carry the owner's old Telegram id as an *integer* —
    `api/studio_api.py::_brainstorm_chat_ids` exists only to read them and
    queries `{"$in": [uid, int(uid)]}` for exactly this reason. The delete
    compared the string form alone and walked straight past every one of them,
    while reporting success. The batch that added collections to the list left
    the type axis open, and the coverage test checks names, not types.
    """
    from app.features.account_delete import delete_account

    numeric = "628544372"
    db["sandy_users"].insert_one({"_id": numeric, "user_id": numeric})
    db["sandy_brainstorms"].insert_one({"chat_id": int(numeric), "topic": "قديم"})
    db["sandy_photos"].insert_one({"chat_id": int(numeric), "cap": "صورة قديمة"})
    db["sandy_tasks"].insert_one({"user_id": numeric, "text": "جديد"})

    delete_account(numeric)

    left = {c: db[c].count_documents({}) for c in db.list_collection_names()
            if db[c].count_documents({}) and c != "sandy_users"}
    assert left == {}, f"legacy numeric-id documents survived the delete: {left}"


def test_releasing_a_robot_wipes_it_and_clears_devices_before_the_node_row(db,
                                                                          monkeypatch):
    """Two orderings, both load-bearing, both invisible to a source-text check.

    The wipe must go out **before** the node row disappears, because the publish
    path checks that the caller owns the node — one line later they do not. And
    the devices must go **before** it too: `ingest_status` looks the node up and
    provisions from its outputs afterwards, so a heartbeat already past that
    lookup would rebuild the whole robot in the registry of the account that
    just released it. Boards heartbeat every few seconds.
    """
    import app.features.node_store as node_store
    import app.integrations.room_device as room_device
    from app.features import device_store
    from app.utils import user_profiles

    seen = []

    class _Client:
        def publish_service(self, topic, payload):
            seen.append(("wipe", db["sandy_nodes"].count_documents({}),
                         db["sandy_devices"].count_documents({})))
            return True

    monkeypatch.setattr(room_device, "get_room_device_client", lambda: _Client())

    with user_profiles.active_user_profile_context(P):
        node_id, _ = _paired_robot_with_a_light()
        out = node_store.unpair_node(node_id)

    assert seen, "the board was released without being told to erase itself"
    _, nodes_at_wipe, devices_at_wipe = seen[0]
    assert nodes_at_wipe == 1, "the wipe went out after the release — undeliverable"
    assert devices_at_wipe == 1, "the fixture is wrong"
    assert out["board_wiped"] is True
    assert db["sandy_nodes"].count_documents({}) == 0
    assert device_store.list_devices() == []


def test_deleting_an_account_also_wipes_the_boards_it_releases(db, monkeypatch):
    """`DELETE /api/account` releases nodes by calling `unpair_node` directly.
    The wipe lived in the *endpoint* for selling a robot, so the strongest erase
    a person can ask for produced the weakest hardware erase — the board kept
    the seller's Wi-Fi name and password."""
    import app.integrations.room_device as room_device
    from app.features import node_store
    from app.features.account_delete import delete_account
    from app.utils import user_profiles

    wiped = []

    class _Client:
        def publish_service(self, topic, payload):
            wiped.append(topic)
            return True

    monkeypatch.setattr(room_device, "get_room_device_client", lambda: _Client())

    with user_profiles.active_user_profile_context(P):
        _paired_robot_with_a_light()
        for n in node_store.list_nodes() or []:
            node_store.unpair_node(str(n.get("node_id") or ""))
    delete_account(U)

    assert any(t.endswith("/factory_reset") for t in wiped), \
        "a deleted account left its boards holding the owner's network"
