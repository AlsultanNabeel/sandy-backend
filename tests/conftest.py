import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "cloud"))


@pytest.fixture(autouse=True)
def _fresh_circuit_breakers(monkeypatch):
    """Every test starts with the model breaker closed.

    It is a module-level singleton, so five failures in one test (a stubbed
    client that raises, a missing key) left the breaker OPEN for every test
    after it — and a later test that drove a real code path through it failed
    or passed depending on the order the suite happened to run in.
    """
    from app.integrations import openai_client
    from app.utils.circuit_breaker import CircuitBreaker

    old = openai_client._cb
    monkeypatch.setattr(openai_client, "_cb", CircuitBreaker(
        name=old.name, failure_threshold=old.failure_threshold,
        recovery_timeout=old.recovery_timeout))
    yield


@pytest.fixture(autouse=True)
def _fresh_account_generations(monkeypatch):
    """Every test reads accounts from its own database.

    `auth_handlers` keeps each account's token generation for a minute; kept across
    tests, an account one test made answered for another test's empty database.
    """
    from app.api import auth_handlers

    monkeypatch.setattr(auth_handlers, "_generations", {})
    yield


@pytest.fixture(autouse=True)
def _a_token_has_an_account(monkeypatch):
    """A token is only ever issued to an account that exists, and the server now refuses
    one whose account is gone. Tests mint tokens directly, so minting one makes sure its
    account row is there (never touching one that is, so a test's generation stays)."""
    from app import db as appdb
    from app.api import auth_handlers

    real = auth_handlers.make_token

    def make_token(role, user_id=None, gen=0):
        db = appdb.get_db()
        if user_id and role != "guest" and db is not None:
            db["sandy_users"].update_one({"_id": user_id}, {"$setOnInsert": {"_id": user_id}},
                                         upsert=True)
        return real(role, user_id=user_id, gen=gen)

    monkeypatch.setattr(auth_handlers, "make_token", make_token)
    yield
