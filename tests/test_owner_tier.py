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
    seen = {}

    def _record(user_id, *, daily_limit, per_min_limit):
        seen["daily"] = daily_limit
        return None

    # Patched on the real modules, not swapped in `sys.modules`: once another
    # test has imported them, `from app.features import usage_store` returns the
    # package attribute and a `sys.modules` swap is never seen.
    monkeypatch.setattr("app.features.usage_store.check_and_record", _record)
    monkeypatch.setattr("app.features.users_store.is_subscriber", lambda _uid: False)

    from app.api import metering
    assert metering.SUBSCRIBER_DAILY > metering.FREE_DAILY
    assert metering.FREE_DAILY == 40, "the free tier moved; this test names it"

    metering.meter_or_error("owner", "u1")
    assert seen["daily"] == metering.SUBSCRIBER_DAILY
    metering.meter_or_error("user", "u1")
    assert seen["daily"] == metering.FREE_DAILY


def test_only_google_decides_the_owner_tier(monkeypatch):
    """Google asks for the role (verified address); email never grants it."""
    import pathlib

    import app.api.email_auth_api as email_api
    import app.api.social_auth_api as social_api

    # Google (verified address) decides the tier; email/password never grants
    # it, because nothing there proves the address.
    src = pathlib.Path(social_api.__file__).read_text(encoding="utf-8")
    assert 'make_token("user"' not in src
    assert "role_for_email" in src
    assert "role_for_email" not in pathlib.Path(email_api.__file__).read_text(encoding="utf-8")
