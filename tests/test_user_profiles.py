from app.utils import user_profiles


def test_reconcile_owner_identity_merges_legacy_ids_not_other_tenants(monkeypatch):
    """voice_ws used to key memory off the raw OWNER_CHAT_ID/legacy env var,
    fragmenting it from the canonical users_store uuid REST/text-chat uses.
    reconcile_owner_identity should merge that (and pre-isolation untagged
    docs) onto the canonical id, while leaving other tenants untouched."""
    import mongomock
    from app.features import users_store

    monkeypatch.setenv("OWNER_CHAT_ID", "628544372")
    monkeypatch.setenv("SANDY_USER_CHAT_ID", "")
    monkeypatch.setattr(user_profiles, "OWNER_CHAT_ID", "628544372")
    monkeypatch.setattr(user_profiles, "LEGACY_OWNER_CHAT_ID", "")
    monkeypatch.setattr(user_profiles, "OWNER_TENANT_ID", "")

    db = mongomock.MongoClient().db
    users_store.init_users_store(db)
    canonical = users_store.get_or_create_owner()
    assert canonical and canonical != "628544372"

    db["sandy_memories"].insert_one({"chat_id": "628544372", "label": "preferences"})
    db["sandy_memories"].insert_one({"label": "preferences"})  # pre-isolation, untagged
    db["sandy_memories"].insert_one({"chat_id": "tenant-B", "label": "preferences"})
    db["sandy_facts"].insert_one({"_id": "f1", "chat_id": "628544372", "text": "owner fact"})
    db["sandy_facts"].insert_one({"_id": "f2", "chat_id": "tenant-B", "text": "other tenant fact"})
    db["memory"].insert_one({"_id": "sandy_memory", "facts": ["legacy"]})  # no user_id

    user_profiles.reconcile_owner_identity(db)

    assert db["sandy_memories"].count_documents({"chat_id": canonical}) == 2
    assert db["sandy_memories"].count_documents({"chat_id": "tenant-B"}) == 1
    assert db["sandy_facts"].find_one({"_id": "f1"})["chat_id"] == canonical
    assert db["sandy_facts"].find_one({"_id": "f2"})["chat_id"] == "tenant-B"
    assert db["memory"].find_one({"_id": "sandy_memory"})["user_id"] == canonical

    # Idempotent: running it again changes nothing further.
    user_profiles.reconcile_owner_identity(db)
    assert db["sandy_memories"].count_documents({"chat_id": canonical}) == 2