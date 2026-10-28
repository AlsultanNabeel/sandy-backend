"""On staging, what the boot guard refuses is also off at its source: no push leaves even
with Apple's keys filled in by mistake, and every error reaches Sentry marked staging."""
from __future__ import annotations

import pytest

from app.services import apns

_KEYS = {"APNS_KEY_P8": "-----BEGIN PRIVATE KEY-----\\nx\\n-----END PRIVATE KEY-----",
         "APNS_KEY_ID": "k", "APNS_TEAM_ID": "t", "APNS_BUNDLE_ID": "b"}


@pytest.fixture
def keys(monkeypatch):
    for k, v in _KEYS.items():
        monkeypatch.setenv(k, v)


def test_production_with_the_keys_pushes(keys, monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    assert apns.is_configured() is True


def test_staging_never_pushes_even_with_the_keys(keys, monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    assert apns.is_configured() is False


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_errors_are_marked_with_their_environment(monkeypatch, env):
    import sentry_sdk

    from app import config
    from app.integrations import error_tracking

    seen = {}
    monkeypatch.setattr(error_tracking, "_started", False)
    monkeypatch.setattr(config, "SENTRY_DSN", "https://k@sentry.example/1")
    monkeypatch.setattr(config, "APP_ENV", env)
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: seen.update(kw))
    assert error_tracking.init_error_tracking() is True
    assert seen["environment"] == env
    for send in (seen["before_send"], seen["before_send_transaction"]):
        assert send({"message": "x"}, None)["tags"] == {"env": env}
        assert send({"tags": {"a": "b"}}, None)["tags"] == {"a": "b", "env": env}
