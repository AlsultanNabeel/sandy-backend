"""A scene's timed revert actually fires — once, for its own owner only."""
from datetime import datetime, timedelta, timezone

import mongomock

from app import db as appdb
from app.features import scene_store as ss
from app.services import scene_timer_runner as runner


def _db():
    d = mongomock.MongoClient().db
    appdb.configure(d)
    return d


def _timer(d, uid, minutes_ago, device="light", value="on"):
    d["sandy_scene_timers"].insert_one({
        "user_id": uid, "device": device, "value": value,
        "fire_at": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)})


def test_due_reverts_fire_once_per_owner(monkeypatch):
    d = _db()
    fired = []

    def fake_actuate(actions):
        from app.utils.user_profiles import current_user_id
        fired.append((current_user_id(), [a["device"] for a in actions]))
        return len(actions), []

    monkeypatch.setattr(ss, "_actuate", fake_actuate)
    try:
        _timer(d, "u1", 2)
        _timer(d, "u2", 1, device="fan", value="off")
        _timer(d, "u1", -30)  # not due yet
        assert runner.run_all_due(d) == 2
        assert sorted(fired) == [("u1", ["light"]), ("u2", ["fan"])]
        # a second tick finds nothing: each revert was claimed and removed
        assert runner.run_all_due(d) == 0
        left = list(d["sandy_scene_timers"].find({}))
        assert len(left) == 1 and left[0]["user_id"] == "u1"
    finally:
        appdb.reset()


def test_one_owner_failing_does_not_stop_the_rest(monkeypatch):
    d = _db()

    def flaky(actions):
        from app.utils.user_profiles import current_user_id
        if current_user_id() == "bad":
            raise RuntimeError("broker down")
        return len(actions), []

    monkeypatch.setattr(ss, "_actuate", flaky)
    try:
        _timer(d, "bad", 1)
        _timer(d, "good", 1)
        assert runner.run_all_due(d) == 1
    finally:
        appdb.reset()


def test_something_schedules_the_runner():
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "cloud/app/bootstrap.py").read_text()
    assert "start_scene_timer_runner(" in src, "nothing fires scene reverts again"
