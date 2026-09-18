"""A partial erase is reported as partial and keeps the account row; the web
chat transcript is erased with everything else."""
import mongomock
from pymongo.errors import PyMongoError

from app import db as appdb
from app.features import account_delete


def _db():
    d = mongomock.MongoClient().db
    d.sandy_users.insert_one({"_id": "u1"})
    d.web_chat_history.insert_one({"_id": "web_chat_u1", "messages": ["hi"]})
    d.web_chat_history.insert_one({"_id": "web_chat_u2", "messages": ["keep"]})
    d.sandy_tasks.insert_one({"user_id": "u1"})
    d.conversations.insert_one({"_id": "c1", "user_id": "u1", "messages": []})
    appdb.configure(d)
    return d


def test_web_chat_history_is_erased():
    d = _db()
    r = account_delete.delete_account("u1")
    assert r["ok"]
    assert d.web_chat_history.find_one({"_id": "web_chat_u1"}) is None
    assert d.web_chat_history.find_one({"_id": "web_chat_u2"}) is not None
    assert d.conversations.find_one({"_id": "c1"}) is None
    appdb.reset()


def test_partial_erase_keeps_the_account(monkeypatch):
    d = _db()
    real = d.__getitem__

    class _Broken:
        def delete_many(self, *_a, **_k):
            raise PyMongoError("down")

    monkeypatch.setattr(type(d), "__getitem__",
                        lambda self, n: _Broken() if n == "sandy_tasks" else real(n))
    r = account_delete.delete_account("u1")
    assert not r["ok"] and r["error"] == "partial"
    assert d.sandy_users.find_one({"_id": "u1"}) is not None
    appdb.reset()
