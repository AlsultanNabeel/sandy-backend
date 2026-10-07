"""The server refuses to start without the settings it cannot guess.

Batch 12: the database name defaulted to the old project's, so a missing config var
opened a database that answered, and the server wrote there.
"""
from __future__ import annotations

import importlib

import pytest


def test_the_database_name_has_no_default(monkeypatch):
    from app import config

    monkeypatch.delenv("MONGODB_DB_NAME", raising=False)
    # The developer's own .env names it; the default is what this is about.
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    try:
        assert importlib.reload(config).MONGODB_DB_NAME == ""
    finally:
        monkeypatch.undo()
        importlib.reload(config)


@pytest.mark.parametrize("env", ["prod", "dev"])
def test_an_address_with_no_name_refuses_to_start_and_says_why(monkeypatch, env):
    from app.integrations import mongodb_store

    monkeypatch.setattr(mongodb_store, "APP_ENV", env)
    monkeypatch.setattr(mongodb_store, "_connect_mongo",
                        lambda uri: pytest.fail("connected with no database name"))
    with pytest.raises(RuntimeError, match="MONGODB_DB_NAME is not set"):
        mongodb_store.init_mongo_connection("mongodb://x/y", "")


# Batch 12: with no encryption key, sensitive fields were written as plain text and the
# only sign was a warning in the log.

@pytest.fixture
def key(monkeypatch):
    """Sets SANDY_LTM_KEY (None: unset) for a fresh read of it."""
    from app.utils import ltm_crypto

    def use(value):
        if value is None:
            monkeypatch.delenv("SANDY_LTM_KEY", raising=False)
        else:
            monkeypatch.setenv("SANDY_LTM_KEY", value)
        monkeypatch.setattr(ltm_crypto, "_init_attempted", False)
        monkeypatch.setattr(ltm_crypto, "_fernet", None)
    yield use
    monkeypatch.undo()
    ltm_crypto._init_attempted, ltm_crypto._fernet = False, None


def _fatal(monkeypatch, env):
    from app import config

    monkeypatch.setattr(config, "APP_ENV", env)
    fatal, _warnings = config.validate_config()
    return [m for m in fatal if "SANDY_LTM_KEY" in m]


def test_prod_without_the_key_refuses_to_start(key, monkeypatch):
    key(None)
    assert "Refusing to start" in _fatal(monkeypatch, "prod")[0]
    key("not-a-fernet-key")
    assert _fatal(monkeypatch, "prod")                 # a broken key seals nothing either


def test_prod_with_the_key_starts(key, monkeypatch):
    from cryptography.fernet import Fernet

    key(Fernet.generate_key().decode())
    assert _fatal(monkeypatch, "prod") == []


@pytest.mark.parametrize("env", ["dev", "test"])
def test_development_and_tests_still_run_without_it(key, monkeypatch, env):
    key(None)
    assert _fatal(monkeypatch, env) == []


def test_bootstrap_stops_on_it(key, monkeypatch):
    from app import bootstrap, config

    key(None)
    monkeypatch.setattr(config, "APP_ENV", "prod")
    with pytest.raises(RuntimeError, match="SANDY_LTM_KEY"):
        bootstrap.bootstrap()
