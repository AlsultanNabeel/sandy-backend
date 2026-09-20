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


def test_a_reply_that_never_finished_cannot_swallow_the_next_question():
    """`replying` used to clear in one place only: Gemini's "turn complete".

    A reply cut short (an interruption, a hiccup on the link) left it raised
    for good, and from then on every short sentence the user said was dropped
    as noise — she simply stopped answering.
    """
    assert "_she_is_really_answering" in SRC, "the stale-reply guard is gone"
    assert '_REPLY_STALE_S' in SRC
    # Cleared on an interruption too, not only on turn_complete.
    inter = SRC.split("response.server_content.interrupted")[1][:400]
    assert 'live_state["replying"] = False' in inter
    # And the flag is judged by real outgoing audio, not by itself.
    assert 'live_state["last_out_at"] = time.monotonic()' in SRC


def test_the_guard_has_a_warm_up_and_a_staleness_limit():
    """Between the user going quiet and her first audio there is a normal wait;
    the guard must hold through it, and let go once she has actually gone
    silent for a while."""
    assert "_REPLY_WARMUP_S" in SRC and "_REPLY_STALE_S" in SRC
