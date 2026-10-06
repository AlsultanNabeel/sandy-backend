"""A scene's timed revert is a `scene` row in sandy_schedules, and it fires once, for its owner."""
from datetime import datetime, timedelta, timezone

import mongomock
import pytest

from app import db as appdb
from app.blocks import init_blocks, schedules
from app.features import scene_store as ss
from app.services import schedule_runner as runner
from app.utils.user_profiles import active_user_profile_context


def _as(uid):
    return active_user_profile_context({"chat_id": uid, "permissions": "all", "relation": "user"})


@pytest.fixture
def d(monkeypatch):
    database = mongomock.MongoClient().db
    appdb.configure(database)
    init_blocks(database)
    monkeypatch.setattr(ss, "_actuate", lambda actions: {"sent": len(actions), "missed": [], "offline": [], "skipped": []})
    yield database
    appdb.reset()


def _movie_for(uid, minutes=30):
    with _as(uid):
        ss.add_scene("movie2", actions=[
            {"device": "light", "value": "10", "for_min": minutes, "then": "100"},
            {"device": "curtain", "value": "close"}])
        return ss.apply_scene("movie2")


def _scene_rows(uid, status=None):
    with _as(uid):
        return schedules.list_schedules("scene", status=status)


def test_applying_a_scene_schedules_its_revert(d):
    r = _movie_for("u1")
    assert r["ok"] and r["timers"] == 1
    rows = _scene_rows("u1", "pending")
    assert len(rows) == 1 and rows[0]["payload"] == {"device": "light", "value": "100"}
    assert d["sandy_scene_timers"].count_documents({}) == 0, "the old collection is not written"
    assert _scene_rows("u2") == [], "another account sees nothing"


def test_reapplying_cancels_the_pending_revert(d):
    _movie_for("u1")
    _movie_for("u1")
    assert len(_scene_rows("u1", "pending")) == 1
    assert len(_scene_rows("u1", "cancelled")) == 1


def test_the_revert_fires_once_for_its_owner_only(d, monkeypatch):
    fired = []

    def fake_actuate(actions):
        from app.utils.user_profiles import current_user_id
        fired.append((current_user_id(), [a["device"] for a in actions]))
        return {"sent": len(actions), "missed": [], "offline": [], "skipped": []}

    _movie_for("u1")
    _movie_for("u2", minutes=90)
    # u1's half hour is up.
    d["sandy_schedules"].update_many({"user_id": "u1"}, {"$set": {
        "fire_at": datetime.now(timezone.utc) - timedelta(minutes=1)}})
    monkeypatch.setattr(ss, "_actuate", fake_actuate)
    assert runner.run_all_due(d) == 1
    assert fired == [("u1", ["light"])]
    assert runner.run_all_due(d) == 0, "a revert fired twice"


def test_something_schedules_the_runner():
    from pathlib import Path
    src = (Path(__file__).resolve().parent.parent / "cloud/app/bootstrap.py").read_text()
    assert "start_schedule_runner(" in src, "nothing fires scene reverts again"
