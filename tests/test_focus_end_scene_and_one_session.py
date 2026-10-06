"""A focus session's end scene belongs to its end, and there is one session at a time.

Audit T5: the phases advance only when something reads the session, so the end scene
(music, light) went off when the user opened the screen the next day, not when it ended.
The owner's decision: a session found over is closed without it.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from brain_fakes import A, brain_db  # noqa: F401 — fixture

from app.features import focus_store, scene_store
from app.utils.user_profiles import active_user_profile_context


@pytest.fixture
def scenes(brain_db, monkeypatch):  # noqa: F811
    applied = []
    monkeypatch.setattr(scene_store, "apply_scene", lambda name: applied.append(name) or {})
    with active_user_profile_context(A):
        yield applied


def _ended(db, ago):
    db["sandy_focus"].update_many({}, {"$set": {
        "started_at": datetime.now(timezone.utc) - ago - timedelta(minutes=25),
        "phase_ends_at": datetime.now(timezone.utc) - ago}})


def test_a_session_found_over_hours_later_is_closed_without_its_end_scene(scenes, brain_db):  # noqa: F811
    assert focus_store.start_focus(focus_min=25, end_scene="relax")["ok"]
    _ended(brain_db, timedelta(hours=9))
    assert focus_store.focus_status() == {"active": False}
    assert scenes == []
    assert brain_db["sandy_focus"].find_one({})["state"] == "done"


def test_a_session_read_as_it_ends_gets_its_end_scene(scenes, brain_db):  # noqa: F811
    assert focus_store.start_focus(focus_min=25, end_scene="relax")["ok"]
    _ended(brain_db, timedelta(seconds=20))
    focus_store.focus_status()
    assert scenes == ["relax"]


def test_finishing_by_hand_still_plays_it(scenes, brain_db):  # noqa: F811
    assert focus_store.start_focus(focus_min=25, end_scene="relax")["ok"]
    assert focus_store.stop_focus(completed=True)["ok"]
    assert scenes == ["relax"]
