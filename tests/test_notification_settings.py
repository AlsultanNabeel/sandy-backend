"""Profile › Notifications (switches, quiet hours) and Profile › Support (feedback)."""
from __future__ import annotations

from datetime import datetime

import pytest
from brain_fakes import brain_db  # noqa: F401

from app.features import notify_prefs
from app.utils.time import USER_TZ


@pytest.fixture()
def c(monkeypatch, brain_db):  # noqa: F811
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    from app.api.server import create_app
    brain_db["sandy_users"].insert_one({"_id": "userA"})
    return create_app(mongo_db=brain_db).test_client()


def _h(uid="userA"):
    from app.api.auth_handlers import make_token
    return {"Authorization": f"Bearer {make_token('user', user_id=uid)}"}


def test_settings_default_on_and_save(c):
    assert c.get("/api/notification-settings", headers=_h()).get_json() == notify_prefs.DEFAULTS
    r = c.post("/api/notification-settings", json={"daily": False, "quiet_start": "23:00",
                                                   "quiet_end": "07:00"}, headers=_h())
    saved = r.get_json()
    assert saved["daily"] is False and saved["reminders"] is True and saved["quiet_end"] == "07:00"
    assert c.post("/api/notification-settings", json={"quiet_start": "25:00"},
                  headers=_h()).status_code == 400


def test_a_switched_off_kind_is_not_pushed_and_quiet_hours_are_silent(c):
    c.post("/api/notification-settings", json={"daily": False, "quiet_start": "23:00",
                                               "quiet_end": "07:00"}, headers=_h())
    night = datetime(2026, 10, 2, 2, 30, tzinfo=USER_TZ)
    noon = datetime(2026, 10, 2, 12, 0, tzinfo=USER_TZ)
    assert notify_prefs.push_rule("userA", "daily_nudge", noon) == (False, False)
    assert notify_prefs.push_rule("userA", "reminder", night) == (True, True)
    assert notify_prefs.push_rule("userA", "reminder", noon) == (True, False)


def test_feedback_is_kept_with_the_app_and_device(c, brain_db):  # noqa: F811
    r = c.post("/api/feedback", json={"text": "التطبيق حلو", "version": "1.0 (7)",
                                      "device": "iPhone14,2", "os": "iOS 18.5"}, headers=_h())
    assert r.status_code == 200
    row = brain_db["sandy_feedback"].find_one({})
    assert row["user_id"] == "userA" and row["device"] == "iPhone14,2" and row["text"] == "التطبيق حلو"
    assert c.post("/api/feedback", json={"text": " "}, headers=_h()).status_code == 400
