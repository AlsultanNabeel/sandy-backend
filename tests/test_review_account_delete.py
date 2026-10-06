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


def test_photo_bytes_in_gridfs_are_erased():
    """Photo bytes live in GridFS (`sandy_photo_files.files/.chunks`), which has
    no user field; only the metadata rows used to be deleted."""
    d = _db()
    for gid, owner in (("g-mine", "u1"), ("g-theirs", "u2")):
        d["sandy_photo_files.files"].insert_one({"_id": gid})
        d["sandy_photo_files.chunks"].insert_one({"files_id": gid, "n": 0, "data": b"x"})
        d.sandy_photos.insert_one({"chat_id": owner, "grid_id": gid})

    assert account_delete.delete_account("u1")["ok"]
    assert d["sandy_photo_files.files"].find_one({"_id": "g-mine"}) is None
    assert d["sandy_photo_files.chunks"].find_one({"files_id": "g-mine"}) is None
    assert d["sandy_photo_files.files"].find_one({"_id": "g-theirs"}) is not None
    assert d.sandy_photos.count_documents({"chat_id": "u1"}) == 0
    appdb.reset()


def _enrolling(d):
    from app.features import speaker_id

    assert speaker_id.start_enrollment("u1")
    assert speaker_id.start_enrollment("u2")
    d.sandy_voice_enroll.update_one({"_id": "u1"}, {"$push": {"clips": b"\x01" * 64}})


def test_voice_learning_clips_go_with_the_account():
    """Raw recordings of the owner's voice, kept while «صوتي» learns, are the most
    personal thing on the server; a deleted account takes them too."""
    d = _db()
    _enrolling(d)
    assert account_delete.delete_account("u1")["ok"]
    assert d.sandy_voice_enroll.find_one({"_id": "u1"}) is None
    assert d.sandy_voice_enroll.find_one({"_id": "u2"}) is not None
    appdb.reset()


def test_voice_learning_clips_go_with_a_reset():
    d = _db()
    _enrolling(d)
    assert account_delete.wipe_account_data("u1")["ok"]
    assert d.sandy_voice_enroll.find_one({"_id": "u1"}) is None
    appdb.reset()


def test_an_abandoned_voice_learning_expires_on_its_own():
    """Learning that never finished (the robot never spoke again) is cleared by the
    database when its window ends, not only when someone next asks about it."""
    from app import bootstrap

    d = _db()
    bootstrap.ensure_indexes()
    ttl = [ix for ix in d.sandy_voice_enroll.index_information().values()
           if ix.get("key") == [("until", 1)]]
    assert ttl and ttl[0].get("expireAfterSeconds") == 0
    appdb.reset()


def _stopped(d):
    from app.brain import stops

    stops.request("u1", "c1", "نص رد ما خلص")
    stops.request("u1", "c2", "رد تاني")
    stops.request("u12", "c1", "حساب تاني بيبلّش بنفس الحروف")


def test_stopped_replies_go_with_the_account():
    """A stop that came after its turn ended is never taken, and it holds reply text."""
    d = _db()
    _stopped(d)
    assert account_delete.delete_account("u1")["ok"]
    assert d.turn_stops.count_documents({"_id": {"$regex": "^u1:"}}) == 0
    assert d.turn_stops.find_one({"_id": "u12:c1"}) is not None
    appdb.reset()


def test_stopped_replies_go_with_a_reset():
    d = _db()
    _stopped(d)
    assert account_delete.wipe_account_data("u1")["ok"]
    assert d.turn_stops.count_documents({"_id": {"$regex": "^u1:"}}) == 0
    appdb.reset()


def test_a_stop_nobody_took_expires():
    from app import bootstrap

    d = _db()
    bootstrap.ensure_indexes()
    ttl = [ix for ix in d.turn_stops.index_information().values()
           if ix.get("key") == [("at", 1)]]
    assert ttl and ttl[0].get("expireAfterSeconds")
    appdb.reset()


def test_a_reset_rebuilds_the_voice_instruction(monkeypatch):
    """The voice instruction is cached per tenant version, on every worker. A reset
    that erases the facts without moving the version kept serving the old ones."""
    from app.api.voice_ws import tools
    from app.utils import prompt_prewarm, thread_pool

    _db()
    tools.clear_instruction_cache()
    built = iter(["حقائق قديمة", "من أول وجديد"])
    monkeypatch.setattr(tools, "_system_instruction_body", lambda *_a: next(built))
    monkeypatch.setattr(thread_pool, "submit_background", lambda fn, *a, **_k: fn(*a))
    monkeypatch.setattr(prompt_prewarm, "schedule", lambda *_a: None)

    assert tools._cached_system_instruction("u1", False) == "حقائق قديمة"
    assert account_delete.wipe_account_data("u1")["ok"]
    assert tools._cached_system_instruction("u1", False) == "من أول وجديد"
    tools.clear_instruction_cache()
    appdb.reset()


def _photo(d):
    d["sandy_photo_files.files"].insert_one({"_id": "g1"})
    d["sandy_photo_files.chunks"].insert_one({"files_id": "g1", "n": 0, "data": b"x"})
    d.sandy_photos.insert_one({"user_id": "u1", "grid_id": "g1"})


def test_photo_rows_stay_when_their_files_could_not_go(monkeypatch):
    """The rows are the only way to find a photo's bytes. Erased after the bytes
    failed, the bytes stayed for ever; kept, the next try finishes the job."""
    d = _db()
    _photo(d)
    real = account_delete._erase_photo_blobs

    def down(*_a):
        raise PyMongoError("down")

    monkeypatch.setattr(account_delete, "_erase_photo_blobs", down)
    r = account_delete.delete_account("u1")
    assert not r["ok"] and r["error"] == "partial"
    assert d.sandy_photos.find_one({"grid_id": "g1"}) is not None
    assert d.sandy_tasks.count_documents({}) == 0   # the rest went

    monkeypatch.setattr(account_delete, "_erase_photo_blobs", real)
    assert account_delete.delete_account("u1")["ok"]
    assert d["sandy_photo_files.files"].find_one({"_id": "g1"}) is None
    assert d.sandy_photos.find_one({"grid_id": "g1"}) is None
    assert d.sandy_users.find_one({"_id": "u1"}) is None
    appdb.reset()


def test_a_partial_reset_or_delete_tells_the_user(monkeypatch):
    """A half-done erase answers in words the app shows: what happened and that
    asking again carries on from where it stopped."""
    from app.api.auth_handlers import make_token
    from app.api.server import create_app

    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    d = _db()
    c = create_app(mongo_db=d).test_client()
    appdb.configure(d)
    monkeypatch.setattr(account_delete, "_erase_photo_blobs",
                        lambda *_a: (_ for _ in ()).throw(PyMongoError("down")))
    _photo(d)
    auth = {"Authorization": f"Bearer {make_token('user', user_id='u1')}"}

    r = c.post("/api/account/reset", json={"confirm": "RESET"}, headers=auth)
    body = r.get_json()
    assert r.status_code == 500 and body["error"] == "partial" and body["message"]
    r = c.delete("/api/account", json={"confirm": "DELETE"}, headers=auth)
    body = r.get_json()
    assert r.status_code == 500 and body["error"] == "partial" and body["message"]
    appdb.reset()
