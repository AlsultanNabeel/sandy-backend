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

from app import db as appdb

SECRET = "x" * 32
EMAIL = "sara@example.com"
PASSWORD = "right-password"


@pytest.fixture
def api(monkeypatch):
    from app.api import auth_handlers
    from app.api.server import create_app
    monkeypatch.setenv("JWT_SECRET", SECRET)
    db = mongomock.MongoClient().db
    appdb.configure(db)
    monkeypatch.setattr(auth_handlers, "_ip_hits", {})
    db.sandy_users.insert_one({"_id": "u1", "provider": "email", "provider_sub": EMAIL,
                               "email": EMAIL, "password_hash": generate_password_hash(PASSWORD)})
    yield create_app(mongo_db=db).test_client(), db
    appdb.reset()


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


# ── H4. A token outlives its account ──────────────────────────────────────────

def _token(uid="u1", gen=None):
    from app.api.auth_handlers import make_token
    return make_token("user", user_id=uid, gen=gen or 0)


def _kinds(c, token):
    return c.get("/api/kinds", headers={"Authorization": f"Bearer {token}"})


def test_a_deleted_account_s_token_is_refused(api):
    c, db = api
    token = _token()
    assert _kinds(c, token).status_code == 200
    from app.features.account_delete import delete_account
    assert delete_account("u1")["ok"]
    assert _kinds(c, token).status_code == 401, \
        "a deleted account's token still talked to the model and wrote rows"


def test_a_token_from_a_revoked_generation_is_refused(api):
    c, db = api
    db.sandy_users.update_one({"_id": "u1"}, {"$set": {"token_gen": 2}})
    assert _kinds(c, _token(gen=1)).status_code == 401
    assert _kinds(c, _token(gen=2)).status_code == 200


def test_the_account_is_read_again_after_a_minute(api, monkeypatch):
    from app.api import auth_handlers
    c, db = api
    now = [1000.0]
    monkeypatch.setattr(auth_handlers, "_clock", lambda: now[0])
    token = _token()
    assert _kinds(c, token).status_code == 200
    db.sandy_users.delete_one({"_id": "u1"})          # gone by another worker's hand
    now[0] += auth_handlers.GENERATION_TTL_S + 1
    assert _kinds(c, token).status_code == 401, "the account was taken as there for over a minute"


def test_a_failed_read_uses_the_last_answer_kept(api, monkeypatch):
    from app.api import auth_handlers
    from app.features import users_store
    c, db = api
    now = [1000.0]
    monkeypatch.setattr(auth_handlers, "_clock", lambda: now[0])
    db.sandy_users.update_one({"_id": "u1"}, {"$set": {"token_gen": 2}})
    assert _kinds(c, _token(gen=2)).status_code == 200

    def broken(_uid):
        raise users_store.GenerationUnreadable("down")
    monkeypatch.setattr(users_store, "token_generation", broken)
    now[0] += auth_handlers.GENERATION_TTL_S + 1
    assert _kinds(c, _token(gen=2)).status_code == 200
    assert _kinds(c, _token(gen=1)).status_code == 401, \
        "a database hiccup let a revoked token through though its answer was kept"


def test_a_failed_read_with_nothing_kept_lets_the_request_through(api, monkeypatch):
    from app.features import users_store

    def broken(_uid):
        raise users_store.GenerationUnreadable("down")
    monkeypatch.setattr(users_store, "token_generation", broken)
    c, _ = api
    assert _kinds(c, _token()).status_code == 200, "a database hiccup signed everyone out"


def test_the_live_call_refuses_a_deleted_account_s_token(api):
    import json

    from app.api.voice_ws import session as sess

    class _WS:
        def __init__(self, hello):
            self._hello = json.dumps(hello)
            self.sent = []

        def receive(self, timeout=None):
            return self._hello

        def send(self, data):
            self.sent.append(json.loads(data))

    _, db = api
    token = _token()
    ok = _WS({"type": "hello", "token": token})
    assert sess._authenticate(ok, "t")
    from app.features.account_delete import delete_account
    assert delete_account("u1")["ok"]
    gone = _WS({"type": "hello", "token": token})
    assert not sess._authenticate(gone, "t")
    assert gone.sent[-1] == {"type": "error", "msg": "auth_fail"}
