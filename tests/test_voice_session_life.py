"""Why a long call stops on its own, and what the vendors actually do.

Three numbers from Google's own Live API documentation, none of which this code
had ever heard of:

* a Live **connection** lasts about ten minutes;
* an audio-only **session** dies at fifteen minutes without context compression;
* and the server sends `GoAway` shortly before it closes a connection, with the
  time remaining.

So a conversation that ran long simply ended — mid sentence, with a log that
looked like a clean exit — and from the room that is indistinguishable from her
deciding to ignore him. Which is exactly the complaint.

The fix is the one the documentation prescribes: keep the resumption handle the
server hands back, listen for `GoAway`, reconnect to the *same* session, and
turn on the sliding window so the session never hits the wall in the first
place. Reconnecting without a handle is a stranger asking who you are.

The audio chunk size is from the same page: **twenty to forty milliseconds**.
The board sends a hundred and twenty-eight at a time, and a coarse frame is a
late frame — the earliest anything can notice speech starting or stopping is the
boundary of whichever frame it is inside.
"""
from __future__ import annotations


def test_the_session_is_told_to_compress_instead_of_dying():
    """Without this an audio session is over at fifteen minutes, full stop."""
    import pathlib

    import app.api.voice_ws.session as session_mod
    from app.api.voice_ws._config import (
        _COMPRESS_TRIGGER_TOKENS,
        _COMPRESS_WINDOW_TOKENS,
    )

    src = pathlib.Path(session_mod.__file__).read_text(encoding="utf-8")
    assert "context_window_compression" in src
    assert "session_resumption" in src
    # Google's numbers: audio accumulates about twenty-five tokens a second.
    assert _COMPRESS_TRIGGER_TOKENS >= 20_000
    assert 0 < _COMPRESS_WINDOW_TOKENS < _COMPRESS_TRIGGER_TOKENS


def test_the_chunk_sent_to_gemini_is_the_size_google_asks_for():
    """Twenty to forty milliseconds. The board's frame is a hundred and
    twenty-eight, and the split costs nothing — the same bytes, more messages."""
    from app.api.voice_ws._config import _CHUNK_BYTES

    ms = _CHUNK_BYTES / 2 / 16000 * 1000
    assert 20 <= ms <= 40, f"{ms:.0f}ms per chunk is outside the documented range"


def test_a_goaway_is_heard_and_the_handle_is_kept():
    """The two together are the whole reconnect. Either alone is useless: a
    handle nobody uses, or a reconnect that has forgotten the conversation."""
    import pathlib

    import app.api.voice_ws.session as session_mod

    src = pathlib.Path(session_mod.__file__).read_text(encoding="utf-8")
    assert 'live_state["goaway"] = True' in src, "the warning is still ignored"
    assert 'live_state["resume"] = handle' in src, "the handle is thrown away"
    assert "reconnecting to the same session" in src


def test_the_reconnect_needs_all_three_conditions():
    """Reconnect when Gemini asked, the robot is still there, and we hold a
    handle. Missing any one of those turns a finished call into a loop."""
    import inspect

    import app.api.voice_ws.session as session_mod

    src = inspect.getsource(session_mod._live_session)
    assert 'live_state.get("goaway")' in src
    assert "resume_handle" in src
    assert "reader.finished" in src, \
        "a robot that hung up would be reconnected to forever"


def test_the_reader_reports_when_the_robot_is_gone():
    """`finished` separates "Gemini hung up" from "the robot did". Without it a
    robot that walked away would be reconnected to forever, and a robot that is
    still waiting would be abandoned."""
    import asyncio

    import app.api.voice_ws.session as session_mod

    class _ClosedSocket:
        def receive(self, timeout=None):
            raise ConnectionError("the robot is gone")

    async def _run() -> None:
        reader = session_mod._DeviceReader(_ClosedSocket())
        assert reader.finished is False, "a fresh reader claims the device left"
        reader.start()
        # The bridge ends when `frames()` returns; that is the same moment.
        async for _ in reader.frames():
            pass
        assert reader.finished is True, \
            "the device went away and nothing recorded it"
        reader.stop()

    asyncio.run(_run())
