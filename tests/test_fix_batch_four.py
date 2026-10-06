"""Fix plan, batch four: the email sign-in limit and tokens of a deleted account.

H3: the limit counted every attempt, right ones too, by the email alone, so anyone who
knew a customer's email could keep them out of their account with five wrong guesses
every quarter of an hour. Now only failures count, per (email, address), with a higher
ceiling per address and per email alone, so switching addresses buys no unlimited
guessing either.
"""
from __future__ import annotations

import mongomock
import pytest
from werkzeug.security import generate_password_hash

SECRET = "x" * 32
EMAIL = "sara@example.com"
PASSWORD = "right-password"


@pytest.fixture
def api(monkeypatch):
    from app.api import auth_handlers
    from app.api.server import create_app
    monkeypatch.setenv("JWT_SECRET", SECRET)
    db = mongomock.MongoClient().db
    monkeypatch.setattr("app.db.get_db", lambda: db)
    monkeypatch.setattr(auth_handlers, "_ip_hits", {})
    db.sandy_users.insert_one({"_id": "u1", "provider": "email", "provider_sub": EMAIL,
                               "email": EMAIL, "password_hash": generate_password_hash(PASSWORD)})
    return create_app(mongo_db=db).test_client(), db


def _login(c, password, ip="1.1.1.1", email=EMAIL):
    return c.post("/api/auth/email/login", json={"email": email, "password": password},
                  headers={"X-Forwarded-For": ip})


# ── H3. The email sign-in limit locks out the account's owner ─────────────────

def test_the_right_password_from_another_address_gets_in(api):
    c, _ = api
    for _ in range(5):
        assert _login(c, "wrong", ip="6.6.6.6").status_code == 401
    assert _login(c, "wrong", ip="6.6.6.6").status_code == 429, "guessing from one address went on"
    assert _login(c, PASSWORD, ip="2.2.2.2").status_code == 200, \
        "five wrong guesses from a stranger locked the owner out of their account"


def test_signing_in_is_not_counted_as_an_attempt(api):
    c, _ = api
    for _ in range(8):
        assert _login(c, PASSWORD).status_code == 200, "signing in rightly used up the limit"


def test_switching_addresses_does_not_open_unlimited_guessing(api):
    from app.api.auth_handlers import EMAIL_LOGIN_LIMITS
    c, _ = api
    ceiling = EMAIL_LOGIN_LIMITS["email_login_acct"]
    for i in range(ceiling):
        assert _login(c, "wrong", ip=f"9.9.{i // 200}.{i % 200}").status_code == 401
    assert _login(c, "wrong", ip="8.8.8.8").status_code == 429, \
        "a new address for every guess guessed without end"


def test_one_address_trying_many_emails_is_stopped(api):
    from app.api.auth_handlers import EMAIL_LOGIN_LIMITS
    c, _ = api
    ceiling = EMAIL_LOGIN_LIMITS["email_login"]
    for i in range(ceiling):
        assert _login(c, "wrong", email=f"user{i}@example.com").status_code == 401
    assert _login(c, "wrong", email="last@example.com").status_code == 429


def test_the_limit_holds_without_the_database(api, monkeypatch):
    from app.api import auth_handlers
    c, _ = api
    monkeypatch.setattr(auth_handlers, "_auth_coll", lambda: None)
    for _ in range(5):
        assert _login(c, "wrong", ip="6.6.6.6").status_code == 401
    assert _login(c, "wrong", ip="6.6.6.6").status_code == 429
    assert _login(c, PASSWORD, ip="2.2.2.2").status_code == 200
