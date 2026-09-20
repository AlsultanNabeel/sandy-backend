"""A call's waiting time has to be measurable from the log, not guessed."""
import pathlib

SRC = (pathlib.Path(__file__).resolve().parents[1]
       / "cloud/app/api/voice_ws/session.py").read_text(encoding="utf-8")


def test_session_open_reports_where_the_time_went():
    assert "session open: seed=" in SRC and "dial=" in SRC, (
        "opening a call no longer says how long the memory seed and dialling "
        "Gemini took — the two things the user waits through before hello")


def test_every_turn_reports_the_wait_before_her_first_audio():
    assert 'state["turn_closed_at"]' in SRC, "the end of the user's turn is not timed"
    assert "first audio %.0fms after the user stopped" in SRC
    # Printed once per turn: the marker is popped, not read.
    assert 'pop("turn_closed_at"' in SRC, "it would print for every audio chunk"
