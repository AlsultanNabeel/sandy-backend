"""Each user has a language of their own, the one the phone sends (`X-Lang`, the app's
setting, first taken from the phone's): what the server says outside a reply — pushes,
the daily nudge, limits, a route's message — comes in it. A reply is in its message's."""
from __future__ import annotations

import mongomock
import pytest

from app.brain import lang


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    db = mongomock.MongoClient().db
    app = create_app(mongo_db=db)
    db["sandy_users"].insert_one({"_id": "u1", "email": "a@b.c"})
    return app.test_client(), db


def _h(uid="u1", language=None):
    from app.api.auth_handlers import make_token
    h = {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}
    if language:
        h["X-Lang"] = language
    return h


def test_the_phone_sends_the_language_and_it_is_kept(env):
    c, db = env
    c.get("/api/features", headers=_h(language="en"))
    assert db["sandy_users"].find_one({"_id": "u1"})["language"] == "en"
    assert lang.for_user("u1") == "en"
    c.get("/api/features", headers=_h(language="ar"))
    assert lang.for_user("u1") == "ar"
    c.get("/api/features", headers=_h(language="fr"))
    assert lang.for_user("u1") == "ar", "a language the app does not speak is not kept"


def test_a_user_with_no_language_is_arabic(env):
    assert lang.for_user("nobody") == "ar"


def test_a_routes_message_comes_in_the_users_language():
    from app.api import metering
    with lang.using("en"):
        assert metering.limit_response("daily_quota_exceeded")["message"].startswith(
            "You've used today's allowance")
    with lang.using("ar"):
        assert metering.limit_response("daily_quota_exceeded")["message"].startswith("خلص رصيدك")


def test_a_reminder_push_is_titled_in_the_users_language(env, monkeypatch):
    from app.services import schedule_runner as R
    _, db = env
    db["sandy_users"].update_one({"_id": "u1"}, {"$set": {"language": "en"}})
    sent = []
    monkeypatch.setattr(R.apns, "send", lambda token, title, text, **k: sent.append(title) or (True, "ok"))
    with lang.using(lang.for_user("u1")):
        R._push(["tok"], "milk", {})
    assert sent == ["Sandy"]


def test_the_daily_question_is_asked_in_the_users_language(env, monkeypatch):
    from app.api import daily_nudge_api as N
    _, db = env
    monkeypatch.setattr(N, "_is_question_day", lambda: True)
    from app.utils.user_profiles import active_user_profile_context
    db["sandy_users"].update_one({"_id": "u1"}, {"$set": {"language": "en"}})
    with active_user_profile_context({"chat_id": "u1", "relation": "user", "permissions": "all"}):
        en = N.get_daily_nudge(db, "u1")
        db["sandy_users"].update_one({"_id": "u1"}, {"$set": {"language": "ar"}})
        ar = N.get_daily_nudge(db, "u1")
    assert en["text"] == lang.PHRASES["nudge_q_unwind"]["en"]
    assert ar["text"] == lang.PHRASES["nudge_q_unwind"]["ar"]


def test_the_language_survives_a_reset_like_the_zone():
    from app.features import account_delete
    assert "language" in account_delete.USER_ROW_KEPT
