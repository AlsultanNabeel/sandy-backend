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
