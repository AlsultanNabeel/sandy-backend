"""Feature switches (`utils/flags.py`): off unless SANDY_FLAGS turns one on for everyone or
for named accounts, and /api/features tells the app which are on for the caller."""
from __future__ import annotations

import mongomock
import pytest

from app.utils import flags


def test_off_by_default(monkeypatch):
    monkeypatch.delenv("SANDY_FLAGS", raising=False)
    assert flags.on("tasks", "u1") is False
    assert flags.enabled_for("u1") == []


def test_on_for_everyone(monkeypatch):
    monkeypatch.setenv("SANDY_FLAGS", '{"tasks": "all"}')
    assert flags.on("tasks", "u1") and flags.on("tasks", "u2")


def test_on_for_one_account_only(monkeypatch):
    monkeypatch.setenv("SANDY_FLAGS", '{"skills": ["u1"], "tasks": "all"}')
    assert flags.on("skills", "u1") is True
    assert flags.on("skills", "u2") is False
    assert flags.on("skills", "") is False
    assert flags.enabled_for("u1") == ["skills", "tasks"]
    assert flags.enabled_for("u2") == ["tasks"]


@pytest.mark.parametrize("raw", ["not json", "[1, 2]", '{"tasks": 3}', '{"tasks": "u1"}'])
def test_a_value_it_cannot_read_turns_that_switch_off(monkeypatch, raw):
    monkeypatch.setenv("SANDY_FLAGS", raw)
    assert flags.on("tasks", "u1") is False


def test_features_route_returns_the_callers_switches(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("SANDY_FLAGS", '{"dev_tools": ["u1"]}')
    monkeypatch.setenv("SANDY_HIDDEN_FEATURES", "weather")
    from app.api.auth_handlers import make_token
    from app.api.server import create_app

    c = create_app(mongo_db=mongomock.MongoClient().db).test_client()

    def get(uid):
        return c.get("/api/features",
                     headers={"Authorization": f"Bearer {make_token('user', user_id=uid)}"}).get_json()
    assert get("u1") == {"hidden": ["weather"], "on": ["dev_tools"]}
    assert get("u2") == {"hidden": ["weather"], "on": []}
