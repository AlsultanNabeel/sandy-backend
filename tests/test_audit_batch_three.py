"""Regressions from the audit plan, batch three: the session, sign-out and switching accounts.

Each test failed before its fix and names what the user saw.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import mongomock
import pytest

SECRET = "x" * 32


@pytest.fixture
def api(monkeypatch):
    from app.api.server import create_app
    monkeypatch.setenv("JWT_SECRET", SECRET)
    db = mongomock.MongoClient().db
    monkeypatch.setattr("app.db.get_db", lambda: db)
    return create_app(mongo_db=db).test_client(), db


def _token(age_hours=0.0, gen=None, uid="u1", life_hours=24 * 7):
    issued = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    claims = {"role": "user", "user_id": uid, "iat": issued, "jti": "j",
              "exp": issued + timedelta(hours=life_hours)}
    if gen is not None:
        claims["gen"] = gen
    return jwt.encode(claims, SECRET, algorithm="HS256")


def _get(c, token):
    return c.get("/api/kinds", headers={"Authorization": f"Bearer {token}"})


# ── K1. A session renews with use instead of ending every week ────────────────

def test_a_day_old_token_comes_back_renewed_on_the_same_generation(api):
    c, db = api
    db.sandy_users.insert_one({"_id": "u1"})
    r = _get(c, _token(age_hours=30))
    assert r.status_code == 200
    fresh = r.headers.get("X-Sandy-Token")
    assert fresh, "a week after sign-in every user was signed out, offline changes and all"
    claims = jwt.decode(fresh, SECRET, algorithms=["HS256"])
    assert claims["user_id"] == "u1" and claims["gen"] == 0 and claims["role"] == "user"


def test_a_fresh_revoked_expired_or_orphan_token_is_not_renewed(api):
    c, db = api
    db.sandy_users.insert_one({"_id": "u1", "token_gen": 2})
    assert not _get(c, _token(age_hours=1, gen=2)).headers.get("X-Sandy-Token")
    assert not _get(c, _token(age_hours=30, gen=1)).headers.get("X-Sandy-Token"), \
        "a revoked token (an older generation) was renewed"
    expired = _get(c, _token(age_hours=200, gen=2))
    assert expired.status_code == 401 and not expired.headers.get("X-Sandy-Token")
    assert not _get(c, _token(age_hours=30, uid="gone")).headers.get("X-Sandy-Token"), \
        "a deleted account's token was renewed"


def test_sign_in_stamps_the_account_s_generation(api, monkeypatch):
    from flask import Flask

    from app.api import email_auth_api
    with Flask(__name__).test_request_context("/"):
        resp, _ = email_auth_api._result_for({"_id": "u1", "token_gen": 3})
    claims = jwt.decode(resp.get_json()["token"], SECRET, algorithms=["HS256"])
    assert claims["gen"] == 3
