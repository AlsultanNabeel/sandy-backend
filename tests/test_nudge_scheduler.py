"""The morning nudge goes out at eight on each user's own clock, and their quiet hours are
read on that clock too, never the server's default zone."""
from __future__ import annotations

from datetime import datetime, timezone

import mongomock
import pytest

from app import db as appdb
from app.api import daily_nudge_api
from app.features import push_tokens_store
from app.services import apns
from app.services import nudge_scheduler as N
from app.utils import time as T


@pytest.fixture
def world(monkeypatch):
    d = mongomock.MongoClient().db
    appdb.configure(d)
    T._cache.clear()
    d["sandy_users"].insert_many([
        {"_id": "riyadh", "timezone": "Asia/Riyadh"},
        # Half an hour off the hour, and quiet from seven to nine on his own clock.
        {"_id": "kolkata", "timezone": "Asia/Kolkata",
         "notifications": {"quiet_start": "07:00", "quiet_end": "09:00"}},
    ])
    sent = []
    monkeypatch.setattr(apns, "is_configured", lambda: True)
    monkeypatch.setattr(push_tokens_store, "user_ids_with_tokens", lambda: ["riyadh", "kolkata"])
    monkeypatch.setattr(push_tokens_store, "tokens_for_user", lambda uid: [f"tok-{uid}"])
    monkeypatch.setattr(daily_nudge_api, "get_daily_nudge", lambda db, uid: {"text": f"صباح {uid}"})

    def send(token, title, body, data=None, silent=False):
        sent.append((token, silent))
        return True, "ok"

    monkeypatch.setattr(apns, "send", send)
    yield d, sent
    T._cache.clear()
    appdb.reset()


def test_each_user_gets_it_at_eight_on_their_own_clock(world):
    d, sent = world
    assert N.run_daily_send(d, datetime(2026, 10, 7, 5, 0, tzinfo=timezone.utc)) == 1   # 08:00 Riyadh
    assert sent == [("tok-riyadh", False)]
    sent.clear()
    assert N.run_daily_send(d, datetime(2026, 10, 7, 2, 30, tzinfo=timezone.utc)) == 1  # 08:00 Kolkata
    # Quiet on his clock (07–09), though it is 04:30 in Cairo.
    assert sent == [("tok-kolkata", True)]


def test_once_a_day_per_user(world):
    d, sent = world
    at = datetime(2026, 10, 7, 5, 0, tzinfo=timezone.utc)
    N.run_daily_send(d, at)
    assert N.run_daily_send(d, at.replace(minute=15)) == 0
    assert len(sent) == 1


def test_nobody_outside_their_morning(world):
    d, sent = world
    assert N.run_daily_send(d, datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)) == 0
    assert sent == []
