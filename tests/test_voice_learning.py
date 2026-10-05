"""She learns the owner's voice from the robot's own mic, then tells owner from guest there.

A print made on a laptop never matched the robot: the clips now come from the robot's
turns while learning is on (started from the app), and are deleted once it is built.
"""
from __future__ import annotations

import mongomock
import pytest

from app import db as appdb
from app.features import speaker_id


@pytest.fixture()
def db(monkeypatch):
    d = mongomock.MongoClient().db
    appdb.configure(d)
    built = []
    monkeypatch.setattr(speaker_id, "enroll_speaker",
                        lambda uid, clips: (built.append(len(clips)) or (True, len(clips), "ok")))
    monkeypatch.setattr("app.utils.tenant_version.bump_for", lambda *a, **k: None)
    yield d, built
    appdb.reset()


CLIP = b"\x01\x00" * 32000          # two seconds


def test_five_robot_turns_teach_her_and_the_audio_is_not_kept(db):
    d, built = db
    assert speaker_id.add_enrollment_clip("u1", CLIP) is None      # not learning: ignored
    assert speaker_id.start_enrollment("u1")
    assert speaker_id.add_enrollment_clip("u1", b"\x01\x00" * 100) is None   # too short
    for _ in range(4):
        assert speaker_id.add_enrollment_clip("u1", CLIP) is None
    assert speaker_id.enrollment_progress("u1") == 4
    ok, n, _ = speaker_id.add_enrollment_clip("u1", CLIP)
    assert ok and n == 5 and built == [5]
    assert d["sandy_voice_enroll"].count_documents({}) == 0
    assert speaker_id.enrollment_progress("u1") is None


def test_who_is_talking_matters_on_the_robot_not_on_the_phone(db, monkeypatch):
    from app.api.voice_ws import speaker
    from app.api.voice_ws.session import _APP_CHANNEL, _ROBOT_CHANNEL

    monkeypatch.setenv("SANDY_REQUIRE_SPEAKER_AUTH", "0")
    monkeypatch.setattr(speaker_id, "has_profile", lambda uid: uid == "u1")
    assert speaker.speaker_gate("u1", _ROBOT_CHANNEL)
    assert not speaker.speaker_gate("u1", _APP_CHANNEL)
    assert not speaker.speaker_gate("u2", _ROBOT_CHANNEL)    # no voiceprint yet