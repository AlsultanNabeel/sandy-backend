"""A daily-question answer is saved under the question it answers, and only a question
she asked: the id used to be written into the profile's field path as it came."""
import mongomock
import pytest


@pytest.fixture()
def c(monkeypatch):
    from app.api.server import create_app

    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    db = mongomock.MongoClient().db
    db["sandy_users"].insert_one({"_id": "u1", "onboarding": {}})
    return create_app(mongo_db=db).test_client(), db


def _h():
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id='u1')}"}


@pytest.mark.parametrize("qid", ["$where", "a.b", "unknown_question"])
def test_an_id_she_never_asked_is_refused(c, qid):
    client, db = c
    r = client.post("/api/daily-nudge/answer", json={"qid": qid, "answer": "x"}, headers=_h())
    assert r.status_code == 400 and r.get_json()["error"] == "unknown_question"
    assert db["sandy_users"].find_one({"_id": "u1"})["onboarding"] == {}


def test_a_real_question_is_saved(c):
    client, db = c
    r = client.post("/api/daily-nudge/answer", json={"qid": "unwind", "answer": "المشي"},
                    headers=_h())
    assert r.status_code == 200
    assert db["sandy_users"].find_one({"_id": "u1"})["onboarding"]["nudge_answers"] == {"unwind": "المشي"}
