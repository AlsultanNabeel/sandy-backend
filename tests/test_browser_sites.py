"""Each site Sandy may open, for one account (`features/browser_sites.py`, behind the `browser`
switch): what she may do there (read only by default, fill, or send after his yes) and the
sign-in the phone sent, sealed with a key of its own for that account and that site, never a
password, and gone with «طلّعها», a reset or the account. Another account sees none of it."""
from __future__ import annotations

import base64
import json

import pytest
from brain_fakes import A, B, brain_db  # noqa: F401

from app.features import browser_sites as S
from app.utils.user_profiles import active_user_profile_context

KEY = base64.urlsafe_b64encode(b"k" * 32).decode()
STATE = {"cookies": [{"name": "sid", "value": "abc123", "domain": ".example.com", "path": "/",
                      "httpOnly": True, "secure": True, "expires": 1893456000, "sameSite": "Lax"}],
         "storage": {"https://app.example.com": {"theme": "dark", "auth_token": "t-1", "password": "hunter2"}}}


@pytest.fixture
def on(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("SANDY_LTM_KEY", KEY)
    monkeypatch.setenv("SANDY_FLAGS", '{"browser": ["userA", "userB"]}')
    S.init_browser_sites(brain_db)
    return brain_db


def _as(who):
    return active_user_profile_context(A if who == "A" else B)


def test_a_site_is_read_only_until_he_says_otherwise(on):
    with _as("A"):
        assert S.level("app.example.com") == S.READ
        assert S.set_level("https://www.app.example.com/x", S.SUBMIT)
        assert S.level("app.example.com") == S.SUBMIT
    with _as("B"):
        assert S.level("app.example.com") == S.READ


def test_an_unknown_level_is_refused(on):
    with _as("A"):
        with pytest.raises(ValueError):
            S.set_level("app.example.com", "pay")


def test_a_sign_in_is_kept_sealed_and_opened_only_for_its_account_and_site(on):
    with _as("A"):
        assert S.save_session("app.example.com", STATE)
        row = on[S.COLLECTION].find_one({"site": "app.example.com"})
        assert "abc123" not in json.dumps(row, default=str) and "dark" not in json.dumps(row, default=str)
        opened = S.session("app.example.com")
        assert opened["cookies"][0]["value"] == "abc123"
        assert opened["storage"]["https://app.example.com"] == {"theme": "dark", "auth_token": "t-1"}
        assert S.session("other.example.com") is None
    with _as("B"):
        assert S.session("app.example.com") is None


def test_a_sealed_sign_in_moved_to_another_site_or_account_does_not_open(on):
    with _as("A"):
        S.save_session("app.example.com", STATE)
    sealed = on[S.COLLECTION].find_one({"site": "app.example.com"})["session"]
    assert S._open(sealed, "userA", "app.example.com")["cookies"]
    assert S._open(sealed, "userB", "app.example.com") is None
    assert S._open(sealed, "userA", "evil.example.com") is None


def test_without_the_servers_key_nothing_is_kept(on, monkeypatch):
    monkeypatch.delenv("SANDY_LTM_KEY")
    with _as("A"):
        assert S.save_session("app.example.com", STATE) is False
        assert on[S.COLLECTION].count_documents({}) == 0


@pytest.mark.parametrize("bad", [
    {"cookies": STATE["cookies"], "password": "x"},
    {"cookies": [{"name": "sid", "value": "1", "domain": "evil.com"}]},
    {"cookies": [{"name": "sid", "value": "1", "domain": "example.com", "password": "x"}]},
    {"cookies": [{"name": "sid", "value": "1", "domain": "com"}]},
    {"storage": {"https://evil.com": {"k": "v"}}},
    {"cookies": "nope"},
    {"cookies": [{"name": "c", "value": "v" * 5000, "domain": "example.com"}]},
])
def test_only_this_sites_cookies_and_storage_are_accepted(on, bad):
    with pytest.raises(ValueError):
        S.clean_state("app.example.com", bad)


def test_a_key_named_like_a_password_never_reaches_the_server(on):
    clean = S.clean_state("app.example.com", {"storage": {"https://app.example.com": {
        "password": "1", "userPassword": "2", "pwd": "3", "passcode": "4", "lang": "ar"}}})
    assert clean["storage"] == {"https://app.example.com": {"lang": "ar"}}


def test_signing_out_forgets_the_sign_in_and_keeps_the_level(on):
    with _as("A"):
        S.set_level("app.example.com", S.FILL)
        S.save_session("app.example.com", STATE)
        assert [s["signed_in"] for s in S.sites()] == [True]
        assert S.sign_out("app.example.com")
        assert S.session("app.example.com") is None
        assert S.sites() == [{"site": "app.example.com", "level": S.FILL, "signed_in": False, "session_at": None}]


def test_the_sites_are_erased_with_the_account_and_a_reset(on):
    from app.features import account_delete
    assert S.COLLECTION in account_delete._BY_USER


# ── The routes ──

@pytest.fixture
def client(on, monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    return create_app(mongo_db=on).test_client()


def _h(uid="userA"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


def test_the_sites_screen_lists_changes_and_signs_out(client):
    assert client.get("/api/browser/sites", headers=_h()).get_json() == {"sites": []}
    r = client.post("/api/browser/sites/app.example.com/session", headers=_h(), json=STATE)
    assert r.status_code == 200 and r.get_json()["site"]["signed_in"] is True
    r = client.patch("/api/browser/sites/app.example.com", headers=_h(), json={"level": "submit"})
    assert r.get_json()["site"]["level"] == "submit"
    assert client.get("/api/browser/sites", headers=_h("userB")).get_json() == {"sites": []}
    assert client.delete("/api/browser/sites/app.example.com/session", headers=_h()).get_json()["site"]["signed_in"] is False


@pytest.mark.parametrize("language, words", [("ar", "مستوى"), ("en", "level")])
def test_a_bad_level_or_session_is_400_in_his_language(client, language, words):
    r = client.patch("/api/browser/sites/app.example.com", headers={**_h(), "X-Lang": language}, json={"level": "x"})
    assert r.status_code == 400 and words in r.get_json()["message"]
    r = client.post("/api/browser/sites/app.example.com/session", headers=_h(), json={"password": "x"})
    assert r.status_code == 400 and r.get_json()["error"] == "bad_session"


def test_a_blocked_site_takes_no_sign_in(client):
    r = client.post("/api/browser/sites/github.com/session", headers=_h(), json={"cookies": []})
    assert r.status_code == 400 and r.get_json()["error"] == "blocked"


def test_without_the_switch_the_routes_are_not_there(client, monkeypatch):
    monkeypatch.setenv("SANDY_FLAGS", "{}")
    assert client.get("/api/browser/sites", headers=_h()).status_code == 404
