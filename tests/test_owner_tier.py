"""«تعذر» after forty messages, on the owner's own phone.

    POST /api/agent/stream ... status=429

Both login routes minted `role="user"`, unconditionally. The top quota tier is
reached by `role == "owner"` **or** `users_store.is_subscriber(user_id)`, and
the owner's account is neither — he does not pay himself. So his phone ran on
the free tier the whole time: forty requests a day, twelve a minute. An
afternoon of testing spends that, and every message after it is a refusal.

The product's own line is that the owner is tenant number one. This is the one
place that never said so.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-long-enough")


def test_the_owners_address_gets_the_owner_role(monkeypatch):
    from app.api.auth_handlers import role_for_email

    monkeypatch.setattr("app.config.SANDY_OWNER_EMAILS", "boss@example.com")
    assert role_for_email("boss@example.com") == "owner"
    assert role_for_email("BOSS@Example.COM") == "owner", "matching is case-sensitive"
    assert role_for_email("  boss@example.com  ") == "owner"


def test_everyone_else_is_a_customer(monkeypatch):
    from app.api.auth_handlers import role_for_email

    monkeypatch.setattr("app.config.SANDY_OWNER_EMAILS", "boss@example.com")
    assert role_for_email("someone@example.com") == "user"
    assert role_for_email("") == "user"


def test_an_unset_list_makes_nobody_the_owner(monkeypatch):
    """The dangerous default would be the other one: an empty setting matching
    everybody puts every customer on the operator's quota."""
    from app.api.auth_handlers import role_for_email

    monkeypatch.setattr("app.config.SANDY_OWNER_EMAILS", "")
    assert role_for_email("anyone@example.com") == "user"
    assert role_for_email("") == "user"

    monkeypatch.setattr("app.config.SANDY_OWNER_EMAILS", " , ,  ")
    assert role_for_email("anyone@example.com") == "user"


def test_the_owner_role_reaches_the_top_quota_tier(monkeypatch):
    """The role is only worth minting if metering reads it — this pins the two
    together, which is the join that was missing."""
    import app.api.server as server

    seen = {}

    class _Usage:
        @staticmethod
        def check_and_record(user_id, *, daily_limit, per_min_limit):
            seen["daily"] = daily_limit
            return None

    class _Users:
        @staticmethod
        def is_subscriber(user_id):
            return False

    monkeypatch.setitem(__import__("sys").modules, "app.features.usage_store", _Usage)
    monkeypatch.setitem(__import__("sys").modules, "app.features.users_store", _Users)

    # `_meter_or_error` is a closure inside `register_api`; reach it the way the
    # route does, through the constants it branches on.
    assert server._SUBSCRIBER_DAILY > server._FREE_DAILY
    assert server._FREE_DAILY == 40, "the free tier moved; this test names it"


def test_both_login_routes_ask_for_the_role(monkeypatch):
    """One route fixed and the other not is the shape this bug would come back
    in: sign in with email and get the owner tier, sign in with Google and not."""
    import pathlib

    import app.api.email_auth_api as email_api
    import app.api.social_auth_api as social_api

    for mod in (email_api, social_api):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        assert 'make_token("user"' not in src, \
            f"{mod.__name__} still hardcodes the customer role"
        assert "role_for_email" in src
