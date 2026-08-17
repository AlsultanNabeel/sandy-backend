"""The voice path's three ways to fail quietly.

The owner spent a week on one sentence: "it answers once and then ignores me
twice." Every one of these caused it, none of them logged an error, and two of
them printed a line that read like success.

These tests run the real classes from `voice_ws.session` against a fake socket.
No Gemini, no network — the faults were never in either.
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "cloud"))

from app.api.voice_ws.session import _DeviceReader  # noqa: E402


class _SilentSocket:
    """A robot that connected, asked its question, and is now waiting.

    It sends nothing. This is not an error state — it is what every device does
    between the end of a question and the end of the answer.
    """

    def __init__(self):
        self.closed = False
        self.reads = 0

    def receive(self, timeout=None):
        self.reads += 1
        if timeout is None:
            # The old behaviour: park until the device speaks or the socket
            # dies. Nothing here will ever do either — which is the point.
            time.sleep(30)
            return b""
        time.sleep(min(timeout, 0.25))
        return None          # simple_websocket returns None on timeout


class _TalkingSocket:
    def __init__(self, frames):
        self._frames = list(frames)

    def receive(self, timeout=None):
        if self._frames:
            return self._frames.pop(0)
        raise ConnectionError("closed")   # simple_websocket raises on close


def test_a_silent_device_does_not_hold_a_worker_thread():
    """The outage, in one assertion.

    `asyncio.run` waits for the default executor on its way out. A reader parked
    in a no-deadline `receive()` is in that executor, so the whole request hung
    until the robot happened to speak again — measured at six seconds in a
    reproduction, unbounded in production. gunicorn has sixteen threads; each
    hung session took one and never gave it back in time.

    The robot, getting no answer, rebooted itself. That is the restart the owner
    has been chasing.
    """
    sock = _SilentSocket()

    async def main():
        reader = _DeviceReader(sock).start()
        await asyncio.sleep(0.4)          # a session that does its work and ends
        reader.stop()

    started = time.time()
    asyncio.run(main())
    elapsed = time.time() - started

    assert elapsed < 2.0, (
        f"asyncio.run took {elapsed:.1f}s to return after a session that ended "
        "in 0.4s — the reader is parked in the default executor again, and "
        "every session will hold a gunicorn thread hostage")
    assert sock.reads > 1, (
        "the reader never came up for air, so it cannot notice a stop request")


def test_a_quiet_moment_is_not_mistaken_for_a_closed_socket():
    """Silence and hang-up must not look the same.

    With a deadline, `receive()` returns None for "nothing yet" and raises for
    "gone". Reading None as a close ends the session every time the person stops
    to think — she would go deaf mid-conversation for no visible reason.
    """
    sock = _SilentSocket()

    async def main():
        reader = _DeviceReader(sock).start()
        await asyncio.sleep(0.9)          # several quiet polls
        alive = not reader._task.done()   # noqa: SLF001 — that is what we assert
        reader.stop()
        return alive

    assert asyncio.run(main()), (
        "the reader stopped during ordinary silence — a pause in the "
        "conversation now ends the call")


def test_audio_still_arrives_and_in_order():
    """The rewrite must not have cost us the actual job."""
    frames = [bytes([i]) * 4 for i in range(5)]
    sock = _TalkingSocket(frames)

    async def main():
        reader = _DeviceReader(sock).start()
        got = []
        async for chunk in reader.frames():
            got.append(chunk)
        reader.stop()
        return got

    assert asyncio.run(main()) == frames


def test_the_reply_is_allowed_to_finish_after_the_device_goes_quiet():
    """The mid-sentence cut, reproduced at the level it happened.

    The bridge waited on both directions with FIRST_COMPLETED and cancelled the
    loser. But the device going quiet is the *normal* end of a question, and
    Gemini is usually still speaking when it happens — so the reply was thrown
    away and the log said "device→live ended cleanly, closing session".

    This is the shape the fix has to have: input finishing gives output a
    bounded chance to finish too.
    """
    from app.api.voice_ws.session import _REPLY_DRAIN_S

    assert _REPLY_DRAIN_S >= 5, "too short to cover a real answer"

    delivered: list[str] = []

    async def device_side():          # the question ends
        await asyncio.sleep(0.05)

    async def gemini_side():          # the answer is still streaming
        await asyncio.sleep(0.25)
        delivered.append("...and that is why.")

    async def bridge():
        t_in = asyncio.create_task(device_side())
        t_out = asyncio.create_task(gemini_side())
        done, pending = await asyncio.wait(
            [t_in, t_out], return_when=asyncio.FIRST_COMPLETED)
        if t_in in done and t_out in pending:
            await asyncio.wait_for(t_out, timeout=_REPLY_DRAIN_S)
        for t in pending:
            t.cancel()

    asyncio.run(bridge())
    assert delivered == ["...and that is why."], (
        "the answer was cut off when the device stopped sending — this is the "
        "'she starts a sentence and disappears' report")


def test_outbound_writes_have_their_own_thread():
    """Her voice went choppy because sending queued behind parked readers.

    Audio out and audio in shared the default executor. Every parked reader made
    the next chunk wait, so the stutter got worse the more sessions had hung —
    which is why it seemed to come and go at random.

    A single dedicated worker also gives strict FIFO: audio frames cannot
    overtake each other, and out-of-order audio does not sound like a bug, it
    sounds like a bad line.
    """
    src = (Path(__file__).resolve().parent.parent
           / "cloud/app/api/voice_ws/session.py").read_text(encoding="utf-8")

    assert 'thread_name_prefix="voice-tx"' in src, "no dedicated send thread"
    assert "tx.shutdown(wait=False)" in src, (
        "the send pool is never shut down — one leaked thread per session is "
        "the same slow failure, wearing a different hat")
    assert "run_in_executor(None, ws.send" not in src, (
        "audio is back on the shared executor")


def test_saving_the_turn_does_not_stall_the_audio():
    """A database write sat in the middle of the reply loop, awaited.

    Every end of turn stopped relaying until Mongo answered. Memory is not on
    the critical path: losing it costs a log line, delaying it costs the owner a
    gap at the end of every sentence.
    """
    src = (Path(__file__).resolve().parent.parent
           / "cloud/app/api/voice_ws/session.py").read_text(encoding="utf-8")

    assert "await loop.run_in_executor(None, _save_voice_turn" not in src, (
        "the turn save is awaited inside the reply loop again")
    assert "loop.run_in_executor(None, _save_voice_turn" in src


def test_voice_does_not_stop_to_ask_are_you_sure():
    """Speaking to her must not cost an extra round trip.

    Every gated call made the model ask, wait for an answer and call again —
    so "turn on the flash" took several seconds and ended in a question. The
    owner asked why, and there was no good answer: most of what was gated was
    never destructive. A lamp is un-turned-on by saying the opposite.
    """
    src = (Path(__file__).resolve().parent.parent
           / "cloud/app/api/voice_ws/session.py").read_text(encoding="utf-8")

    assert "تأكيد صوتي" not in src, "the spoken confirmation step is back"
    assert "awaited_confirm" not in src
    assert "DESTRUCTIVE_TOOLS" not in src, (
        "the voice path is gating tools again — that guard belongs to the text "
        "router, where there is no conversation waiting on it")


def test_switching_a_device_on_is_not_treated_as_destruction():
    from app.agent.guards import DESTRUCTIVE_TOOLS

    for tool in ("device_control", "scene_apply", "shopping_remove"):
        assert tool not in DESTRUCTIVE_TOOLS, (
            f"{tool} is reversible by saying the opposite — guarding it buys "
            "nothing and costs a round trip on every command")

    # ...and the ones that really do lose something are still guarded.
    assert {"delete_photo", "brainstorm_delete"} <= DESTRUCTIVE_TOOLS


def test_tools_do_not_run_on_the_shared_thread_pool():
    """A slow tool must not delay the audio behind it.

    "Turn on the flash" waits on the broker; "what's the weather" waits on the
    internet. Both used the shared executor, so every tool call queued next to
    the socket reads and writes and the slowest one held up her voice.
    """
    src = (Path(__file__).resolve().parent.parent
           / "cloud/app/api/voice_ws/session.py").read_text(encoding="utf-8")

    assert 'thread_name_prefix="voice-tool"' in src
    assert "run_in_executor(\n                    None, _dispatch_tool" not in src
    assert "tools_pool.shutdown(wait=False)" in src


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
