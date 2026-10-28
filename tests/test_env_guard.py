"""The boot guard (`utils/env_guard.py`): a staging server never touches production — not
its database, not its broker, no pushes, no store webhooks, no firmware — and production
never runs on a database marked staging."""
from __future__ import annotations

import logging

import mongomock
import pytest

from app.utils import env_guard as G

PROD_HOST = "aea5cd5ef716450d99e8f06cf1eaba01.s1.eu.hivemq.cloud"
CLEAN = {"APP_ENV": "staging", "MONGODB_DB_NAME": "sandy-staging"}


def _db():
    return mongomock.MongoClient().db


def _problems(**env):
    return G.problems({**CLEAN, **env})


def test_a_clean_staging_server_boots_and_marks_its_database():
    db = _db()
    G.check(db, CLEAN)
    assert db[G.MARKER].find_one({"_id": "env"})["env"] == "staging"
    G.check(db, CLEAN)  # and again: the mark is its own


def test_staging_on_the_production_database_name_is_refused():
    assert any("MONGODB_DB_NAME" in p for p in _problems(MONGODB_DB_NAME="sandy-app"))


def test_staging_on_a_database_marked_production_is_refused():
    db = _db()
    db[G.MARKER].insert_one({"_id": "env", "env": "prod"})
    with pytest.raises(G.EnvGuardError, match="prod"):
        G.check(db, CLEAN)


def test_production_on_a_database_marked_staging_is_refused():
    db = _db()
    db[G.MARKER].insert_one({"_id": "env", "env": "staging"})
    with pytest.raises(G.EnvGuardError, match="staging"):
        G.check(db, {"APP_ENV": "prod", "MONGODB_DB_NAME": "sandy-app"})


def test_production_marks_a_new_database_and_boots_on_its_own():
    db = _db()
    G.check(db, {"APP_ENV": "prod", "MONGODB_DB_NAME": "sandy-app"})
    assert db[G.MARKER].find_one({"_id": "env"})["env"] == "prod"
    G.check(db, {"APP_ENV": "prod", "MONGODB_DB_NAME": "sandy-app"})


def test_staging_on_the_production_broker_login_is_refused():
    found = _problems(SANDY_MQTT_HOST=PROD_HOST.upper(), SANDY_MQTT_USER="sandy-server")
    assert any("SANDY_MQTT_HOST" in p for p in found)


def test_staging_with_its_own_broker_or_none_boots():
    assert _problems() == []
    assert _problems(SANDY_MQTT_HOST="other.s1.eu.hivemq.cloud", SANDY_MQTT_USER="staging") == []


def test_the_production_broker_inside_the_board_logins_is_refused():
    raw = '{"8421": {"host": "%s", "user": "board", "pass": "s3cret"}}' % PROD_HOST
    found = _problems(SANDY_BROKER_CREDS=raw)
    assert any("SANDY_BROKER_CREDS" in p for p in found)
    assert not any("s3cret" in p for p in found)


@pytest.mark.parametrize("name", ["APNS_KEY_P8", "APNS_KEY_ID", "APNS_TEAM_ID", "APNS_BUNDLE_ID",
                                  "APNS_USE_SANDBOX", "REVENUECAT_WEBHOOK_AUTH",
                                  "SANDY_FIRMWARE_TOKEN"])
def test_staging_with_a_production_only_setting_is_refused(name):
    found = _problems(**{name: "secret-value"})
    assert any(name in p for p in found)
    assert not any("secret-value" in p for p in found)


def test_an_empty_setting_counts_as_unset():
    assert _problems(APNS_KEY_ID="  ", SANDY_FIRMWARE_TOKEN="") == []


def test_production_may_have_all_of_them():
    assert G.problems({"APP_ENV": "prod", "MONGODB_DB_NAME": "sandy-app", "APNS_KEY_ID": "k",
                       "SANDY_MQTT_HOST": PROD_HOST, "SANDY_MQTT_USER": "sandy-server"}) == []


def test_every_problem_is_named_at_once_and_no_secret_is_logged(caplog):
    env = {**CLEAN, "MONGODB_DB_NAME": "sandy-app", "APNS_KEY_P8": "-----BEGIN-----",
           "SANDY_MQTT_PASS": "hunter2", "SANDY_MQTT_HOST": PROD_HOST, "SANDY_MQTT_USER": "sandy-server"}
    with caplog.at_level(logging.DEBUG), pytest.raises(G.EnvGuardError) as err:
        G.check(_db(), env)
    text = str(err.value) + caplog.text
    assert "MONGODB_DB_NAME" in text and "APNS_KEY_P8" in text and "SANDY_MQTT_HOST" in text
    assert "BEGIN" not in text and "hunter2" not in text


def test_a_refused_staging_never_marks_the_database():
    db = _db()
    with pytest.raises(G.EnvGuardError):
        G.check(db, {**CLEAN, "SANDY_FIRMWARE_TOKEN": "x"})
    assert db[G.MARKER].count_documents({}) == 0


def test_boot_refuses_before_anything_else_runs(monkeypatch):
    from app import bootstrap as B
    ran = []
    monkeypatch.setattr(B, "ensure_indexes", lambda: ran.append("indexes"))
    monkeypatch.setattr(B, "write_google_credentials", lambda: ran.append("google"))
    monkeypatch.setattr("app.config.validate_config", lambda: ([], []))
    monkeypatch.setattr("app.db.get_db", lambda: _db())
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("MONGODB_DB_NAME", "sandy-app")
    with pytest.raises(G.EnvGuardError):
        B.bootstrap(app_env="staging")
    assert ran == []
