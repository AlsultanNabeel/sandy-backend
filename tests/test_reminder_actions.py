"""Acting on a reminder the moment it fires: snooze, done, delete.

These are what the notification buttons on the phone (and the swipe actions on
the row) call, so the two things worth pinning down are the recurring cases —
a snooze must not drag a daily reminder ten minutes later every day, and "done"
must retire *this* occurrence only — and that none of it reaches another user's
reminder, which is the one bug here that is not merely annoying.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import mongomock
import pytest
from flask import Flask

from app import db as appdb
from app.api.auth_handlers import make_token
from app.api.productivity_api import register_productivity_api
from app.utils.time import USER_TZ

_COLL = "sandy_reminders"


@pytest.fixture
def api(monkeypatch):
    """A Flask test client over a mongomock db, plus headers for two users."""
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    d = mongomock.MongoClient().db
    appdb.configure(d)
    app = Flask(__name__)
    register_productivity_api(app, mongo_db=d)
    client = app.test_client()
    owner = {"Authorization": f"Bearer {make_token('user', user_id='u1')}"}
    other = {"Authorization": f"Bearer {make_token('user', user_id='u2')}"}
    try:
        yield client, d, owner, other
    finally:
        appdb.reset()


def _create(client, headers, *, text="دوا الضغط", when=None, recurrence=""):
    when = when or (datetime.now(USER_TZ) + timedelta(days=1)).replace(
        hour=8, minute=0, second=0, microsecond=0)
    body = {"text": text, "remind_at": when.isoformat()}
    if recurrence:
        body["recurrence"] = recurrence
    assert client.post("/api/reminders", headers=headers, json=body).status_code == 200
    return client, when


def _doc(d):
    return d[_COLL].find_one({})


def _aware(value):
    """mongomock hands back naive datetimes that are really UTC."""
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _force_remind_at(d, when):
    d[_COLL].update_many({}, {"$set": {"remind_at": when.astimezone(timezone.utc)}})


# ── snooze ───────────────────────────────────────────────────────────────────

def test_snooze_moves_the_time_and_keeps_the_recurrence(api):
    client, d, owner, _ = api
    _create(client, owner, recurrence="RRULE:FREQ=DAILY")

    r = client.patch(f"/api/reminders/{_doc(d)['_id']}", headers=owner,
                     json={"action": "snooze", "minutes": 15})
    assert r.status_code == 200
    assert r.get_json()["is_recurring"] is True

    doc = _doc(d)
    assert doc["recurrence"] == "RRULE:FREQ=DAILY", "the snooze ate the rule"
    assert doc["send_state"] == "pending"
    delta = _aware(doc["remind_at"]) - datetime.now(timezone.utc)
    assert timedelta(minutes=13) < delta < timedelta(minutes=16)


def test_a_snoozed_daily_reminder_comes_back_on_its_own_hour(api):
    """The drift bug: anchoring the rule at the snoozed time would make a daily
    eight o'clock ring at 8:10 tomorrow, 8:20 the day after, forever."""
    client, d, owner, _ = api
    _create(client, owner, recurrence="RRULE:FREQ=DAILY")
    eight = (datetime.now(USER_TZ) - timedelta(days=3)).replace(
        hour=8, minute=0, second=0, microsecond=0)
    _force_remind_at(d, eight)          # it rang, three days ago, at eight

    rid = _doc(d)["_id"]
    assert client.patch(f"/api/reminders/{rid}", headers=owner,
                        json={"action": "snooze", "minutes": 10}).status_code == 200
    assert _aware(_doc(d)["series_at"]) == eight.astimezone(timezone.utc)

    # The snooze rang too and went stale; the next read rolls the series on.
    _force_remind_at(d, datetime.now(timezone.utc) - timedelta(minutes=30))
    items = client.get("/api/reminders", headers=owner).get_json()["items"]
    assert len(items) == 1
    nxt = datetime.fromisoformat(items[0]["remind_at"]).astimezone(USER_TZ)
    assert (nxt.hour, nxt.minute) == (8, 0), "the snooze dragged the series along"
    assert _doc(d)["series_at"] is None, "the snooze anchor outlived the snooze"


def test_a_snooze_with_no_minutes_uses_the_house_default(api):
    """The lock-screen button has no room to ask, so it sends none."""
    client, d, owner, _ = api
    _create(client, owner)
    r = client.patch(f"/api/reminders/{_doc(d)['_id']}", headers=owner,
                     json={"action": "snooze"})
    assert r.status_code == 200
    delta = _aware(_doc(d)["remind_at"]) - datetime.now(timezone.utc)
    assert timedelta(minutes=8) < delta < timedelta(minutes=11)


def test_a_snooze_outside_the_sane_range_is_refused(api):
    client, d, owner, _ = api
    _create(client, owner)
    before = _aware(_doc(d)["remind_at"])
    rid = _doc(d)["_id"]
    for minutes in (0, -5, 60 * 24 * 30, "soon"):
        r = client.patch(f"/api/reminders/{rid}", headers=owner,
                         json={"action": "snooze", "minutes": minutes})
        assert r.status_code == 400 and r.get_json()["error"] == "bad_minutes"
    assert _aware(_doc(d)["remind_at"]) == before


# ── done ─────────────────────────────────────────────────────────────────────

def test_done_on_a_recurring_reminder_leaves_the_next_occurrence(api):
    client, d, owner, _ = api
    _, when = _create(client, owner, recurrence="RRULE:FREQ=DAILY")

    rid = _doc(d)["_id"]
    r = client.patch(f"/api/reminders/{rid}", headers=owner, json={"action": "done"})
    assert r.status_code == 200
    payload = r.get_json()
    assert payload["is_recurring"] is True

    nxt = datetime.fromisoformat(payload["remind_at"]).astimezone(USER_TZ)
    assert (nxt.hour, nxt.minute) == (8, 0)
    assert nxt.date() == (when + timedelta(days=1)).date(), "it skipped more than today"

    doc = _doc(d)
    assert doc["send_state"] == "pending", "a recurring reminder was retired by one done"
    assert len(client.get("/api/reminders", headers=owner).get_json()["items"]) == 1


def test_done_on_a_one_off_retires_it(api):
    client, d, owner, _ = api
    _create(client, owner)

    r = client.patch(f"/api/reminders/{_doc(d)['_id']}", headers=owner,
                     json={"action": "done"})
    assert r.status_code == 200
    assert r.get_json()["remind_at"] == "", "a one-off reported a next time"
    assert _doc(d)["send_state"] == "sent"
    assert client.get("/api/reminders", headers=owner).get_json()["items"] == []


def test_done_on_a_rule_that_has_run_out_retires_it(api):
    client, d, owner, _ = api
    until = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y%m%dT%H%M%SZ")
    _create(client, owner, recurrence=f"RRULE:FREQ=DAILY;UNTIL={until}")

    r = client.patch(f"/api/reminders/{_doc(d)['_id']}", headers=owner,
                     json={"action": "done"})
    assert r.status_code == 200 and r.get_json()["remind_at"] == ""
    assert _doc(d)["send_state"] == "sent"


def test_an_unknown_action_changes_nothing(api):
    client, d, owner, _ = api
    _create(client, owner)
    before = _aware(_doc(d)["remind_at"])
    r = client.patch(f"/api/reminders/{_doc(d)['_id']}", headers=owner,
                     json={"action": "postpone"})
    assert r.status_code == 400 and r.get_json()["error"] == "unknown_action"
    assert _aware(_doc(d)["remind_at"]) == before


def test_editing_the_time_clears_a_leftover_snooze_anchor(api):
    """Snooze, then move the reminder by hand: the new time is the series."""
    client, d, owner, _ = api
    _create(client, owner, recurrence="RRULE:FREQ=DAILY")
    rid = _doc(d)["_id"]
    assert client.patch(f"/api/reminders/{rid}", headers=owner,
                        json={"action": "snooze", "minutes": 10}).status_code == 200
    assert _doc(d)["series_at"] is not None

    moved = (datetime.now(USER_TZ) + timedelta(days=2)).replace(
        hour=21, minute=30, second=0, microsecond=0)
    assert client.patch(f"/api/reminders/{rid}", headers=owner,
                        json={"remind_at": moved.isoformat()}).status_code == 200
    assert _doc(d)["series_at"] is None


# ── delete ───────────────────────────────────────────────────────────────────

def test_delete_removes_the_reminder(api):
    client, d, owner, _ = api
    _create(client, owner)
    assert client.delete(f"/api/reminders/{_doc(d)['_id']}",
                         headers=owner).status_code == 200
    assert d[_COLL].count_documents({}) == 0


# ── isolation ────────────────────────────────────────────────────────────────

def test_none_of_the_actions_reach_another_users_reminder(api):
    client, d, owner, other = api
    _create(client, owner, recurrence="RRULE:FREQ=DAILY")
    rid = _doc(d)["_id"]
    before = _aware(_doc(d)["remind_at"])

    for body in ({"action": "snooze", "minutes": 10}, {"action": "done"}):
        r = client.patch(f"/api/reminders/{rid}", headers=other, json=body)
        assert r.status_code == 400 and r.get_json()["error"] == "not_found"
    assert client.delete(f"/api/reminders/{rid}", headers=other).status_code == 400

    doc = _doc(d)
    assert doc is not None and doc["user_id"] == "u1"
    assert _aware(doc["remind_at"]) == before
    assert doc["send_state"] == "pending"
    assert client.get("/api/reminders", headers=other).get_json()["items"] == []
