"""The subscription mirrors what the store says, in the order it happened.

A late expiry used to cancel a renewal that came after it, a failed card ended access at
once (the owner's decision is three days' grace), a trial that expired stayed «trialing»,
and a write that failed still answered 200, so the store never sent it again."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import mongomock
import pytest

AUTH = "Bearer hook-secret"


@pytest.fixture()
def hook(monkeypatch):
    from app.api.server import create_app

    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    monkeypatch.setenv("REVENUECAT_WEBHOOK_AUTH", AUTH)
    db = mongomock.MongoClient().db
    db["sandy_users"].insert_one({"_id": "u1", "subscription": {"status": "none"}})
    c = create_app(mongo_db=db).test_client()

    def send(kind, at, *, ends=None, trial=False, user="u1"):
        event = {"type": kind, "app_user_id": user, "product_id": "monthly",
                 "event_timestamp_ms": int(at.timestamp() * 1000),
                 "expiration_at_ms": int((ends or at + timedelta(days=30)).timestamp() * 1000)}
        if trial:
            event["period_type"] = "TRIAL"
        return c.post("/webhook/revenuecat", json={"event": event},
                      headers={"Authorization": AUTH})
    return send, db


def _live(db):
    from app.features import users_store
    return users_store.is_subscriber("u1")


def test_a_late_expiry_does_not_cancel_the_renewal_after_it(hook):
    send, db = hook
    now = datetime.now(timezone.utc)
    assert send("RENEWAL", now).status_code == 200
    assert send("EXPIRATION", now - timedelta(hours=1), ends=now - timedelta(hours=1)).status_code == 200
    assert _live(db)


def test_a_failed_card_keeps_access_three_days(hook, monkeypatch):
    from app.features import users_store

    send, db = hook
    now = datetime.now(timezone.utc)
    send("INITIAL_PURCHASE", now - timedelta(days=30), ends=now - timedelta(minutes=1))
    send("BILLING_ISSUE", now)
    assert _live(db)
    later = now + timedelta(days=3, minutes=5)
    monkeypatch.setattr(users_store, "_now", lambda: later)
    assert not _live(db)


def test_an_expired_trial_is_expired(hook):
    send, db = hook
    now = datetime.now(timezone.utc)
    send("INITIAL_PURCHASE", now - timedelta(days=3), trial=True)
    send("EXPIRATION", now, ends=now, trial=True)
    assert db["sandy_users"].find_one({"_id": "u1"})["subscription"]["status"] == "expired"


def test_a_write_that_failed_is_sent_again(hook, monkeypatch):
    from app.features import users_store

    send, _ = hook

    def _down(*a, **k):
        raise RuntimeError("database down")
    monkeypatch.setattr(users_store, "set_subscription", _down)
    assert send("RENEWAL", datetime.now(timezone.utc)).status_code == 500


def test_an_unknown_user_is_acknowledged_and_logged(hook, caplog):
    send, _ = hook
    r = send("RENEWAL", datetime.now(timezone.utc), user="anonymous-123")
    assert r.status_code == 200
    assert "anonymous-123" in caplog.text
