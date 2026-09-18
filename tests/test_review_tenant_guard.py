"""An update cannot move a document out of its tenant."""
import mongomock

from app.utils.tenant_db import ScopedCollection


def _coll():
    raw = mongomock.MongoClient().db.things
    raw.insert_many([{"_id": 1, "user_id": "a", "n": 0},
                     {"_id": 2, "user_id": "b", "n": 0}])
    return raw, ScopedCollection(raw, "a", bump=False)


def test_set_of_scope_field_is_forced_to_tenant():
    raw, c = _coll()
    c.update_one({"_id": 1}, {"$set": {"user_id": "b", "n": 1}})
    assert raw.find_one({"_id": 1}) == {"_id": 1, "user_id": "a", "n": 1}


def test_unset_and_rename_of_scope_field_are_dropped():
    raw, c = _coll()
    c.update_one({"_id": 1}, {"$unset": {"user_id": ""}, "$inc": {"n": 1}})
    import pytest
    with pytest.raises(ValueError):
        c.update_many({}, {"$rename": {"user_id": "owner"}})
    assert raw.find_one({"_id": 1}) == {"_id": 1, "user_id": "a", "n": 1}


def test_upsert_with_setoninsert_stays_in_tenant():
    raw, c = _coll()
    c.update_one({"_id": 3}, {"$setOnInsert": {"user_id": "b"}, "$set": {"n": 5}},
                 upsert=True)
    assert raw.find_one({"_id": 3})["user_id"] == "a"


def test_find_one_and_update_guarded():
    raw, c = _coll()
    c.find_one_and_update({"_id": 1}, {"$set": {"user_id": "b"}})
    assert raw.find_one({"_id": 1})["user_id"] == "a"


def test_other_tenant_untouched():
    raw, c = _coll()
    c.update_many({}, {"$set": {"n": 9}})
    assert raw.find_one({"_id": 2})["n"] == 0


def test_pipeline_update_guarded():
    _, c = _coll()
    stages = c._guard_update([{"$set": {"user_id": "b"}}, {"$unset": ["user_id", "n"]}])
    assert stages == [{"$set": {"user_id": "a"}}, {"$unset": ["n"]}]
