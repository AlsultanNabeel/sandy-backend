"""A reminder made or changed anywhere but the phone (the robot, the app's call, Sandy in
chat) reaches the phone's notifications: a silent background push tells it to sync."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, brain_db  # noqa: F401

from app.blocks import _base, schedules
from app.features import push_tokens_store
from app.services import apns, schedule_sync
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def pushes(monkeypatch, brain_db):  # noqa: F811
    sent = []
    monkeypatch.setattr(apns, "is_configured", lambda: True)
    monkeypatch.setattr(push_tokens_store, "tokens_for_user", lambda uid: [f"tok-{uid}"])
    monkeypatch.setattr(apns, "send_background", lambda token, data: sent.append((token, data)) or (True, "ok"))
    monkeypatch.setattr(schedule_sync, "DEBOUNCE_S", 0)
    monkeypatch.setattr(schedule_sync, "submit_background", lambda fn, *a, **k: fn(*a))
    monkeypatch.setattr(schedule_sync, "_waiting", set())   # another test's send may still wait
    with active_user_profile_context(A):
        yield sent


LATER = datetime.now(timezone.utc) + timedelta(hours=1)


def test_a_new_reminder_tells_the_phone(pushes):
    schedules.add("reminder", "الدوا", LATER)
    assert pushes == [("tok-userA", {"sync": "schedules"})]


def test_a_change_and_a_delete_tell_it_too(pushes):
    sid = schedules.add("reminder", "الدوا", LATER)
    schedules.update(sid, fire_at=LATER + timedelta(minutes=5))
    schedules.delete(sid)
    assert len(pushes) == 3


def test_an_undo_tells_it(pushes):
    with _base.journal() as effects:
        schedules.add("reminder", "الدوا", LATER)
    pushes.clear()
    _base.undo(effects)
    assert len(pushes) == 1


def test_what_the_phone_does_not_ring_is_not_pushed(pushes):
    schedules.add("scene", "light → off", LATER, {"device": "light", "value": "off"})
    assert pushes == []


def test_without_push_keys_nothing_is_sent(pushes, monkeypatch):
    monkeypatch.setattr(apns, "is_configured", lambda: False)
    schedules.add("reminder", "الدوا", LATER)
    assert pushes == []
