from app.utils import user_profiles


class _FakeCollection:
    def __init__(self):
        self.docs = {}

    def find_one(self, query):
        return self.docs.get(query.get("_id"))

    def replace_one(self, query, document, upsert=False):
        self.docs[query.get("_id")] = dict(document)

    def find(self, query):
        return list(self.docs.values())


class _FakeMongoDB:
    def __init__(self):
        self.collections = {}

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = _FakeCollection()
        return self.collections[name]


def test_guest_profile_defaults_and_name_capture(monkeypatch):
    monkeypatch.setattr(user_profiles, "OWNER_CHAT_ID", "")
    db = _FakeMongoDB()

    profile, created = user_profiles.ensure_user_profile(123, mongo_db=db)

    assert created is True
    assert profile["relation"] == "guest"
    assert profile["tone"] == "formal"
    assert profile["permissions"] == "chat-only"

    assert user_profiles.extract_profile_name("اسمي أحمد") == "أحمد"

    updated = user_profiles.update_user_profile(123, {"name": "أحمد"}, mongo_db=db)
    assert updated["name"] == "أحمد"


def test_owner_profile_gets_full_permissions(monkeypatch):
    monkeypatch.setattr(user_profiles, "OWNER_CHAT_ID", "999")
    db = _FakeMongoDB()

    profile, created = user_profiles.ensure_user_profile(999, mongo_db=db)

    assert created is False
    assert profile["relation"] == "owner"
    assert profile["tone"] == "casual"
    assert profile["permissions"] == "all"


def test_legacy_owner_chat_id_still_counts_as_owner(monkeypatch):
    monkeypatch.setattr(user_profiles, "OWNER_CHAT_ID", "")
    monkeypatch.setattr(user_profiles, "LEGACY_OWNER_CHAT_ID", "777")
    db = _FakeMongoDB()

    assert user_profiles.is_owner_chat_id(777) is True

    profile, created = user_profiles.ensure_user_profile(777, mongo_db=db)

    assert created is False
    assert profile["relation"] == "owner"
    assert profile["permissions"] == "all"


def test_prompt_sections_reflect_tone_and_privacy(monkeypatch):
    monkeypatch.setattr(user_profiles, "OWNER_CHAT_ID", "")

    sections = user_profiles.build_user_profile_prompt_sections(
        {
            "chat_id": "123",
            "name": "نور",
            "relation": "guest",
            "tone": "formal",
            "permissions": "chat-only",
        }
    )

    assert "formal" in sections["user_profile_block"]
    assert "هذا خاص بنبيل" in sections["user_profile_priority_line"]
    assert user_profiles.is_sensitive_domain_request("شو مهامي اليوم") is True
    assert user_profiles.is_sensitive_domain_request("احكيلي نكتة") is False


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