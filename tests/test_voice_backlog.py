"""Four questions in two seconds, and an answer to none of them.

The log, after the turn control was fixed:

    07:08:48.887  first audio frame forwarded to Gemini
    07:08:48.893  turn closed after 2.3s of speech      ← six milliseconds later
    07:08:48.903  turn closed after 4.2s of speech
    07:08:49.775  turn closed after 2.7s of speech
    07:08:50.656  turn closed after 0.8s of speech
    ...
    turn done: heard='كيف حالك صباح الخير؟'  replied=0 chars

Ten seconds of speech went past in two seconds of wall clock, because it had
been sitting in the reader's buffer while the session spent six to nine seconds
opening — the robot records from the wake word, and the setup behind it is not
instant. Drained at machine speed, the pauses *inside one sentence* looked like
the end of four separate questions, and each turn we opened cancelled the reply
to the one before it. She heard him perfectly. She never got to finish a word.

Two fixes, one for each half:

* the instruction that took those seconds is cached per tenant version, so
  there is no backlog to drain after the first call;
* and while a backlog exists, the turn is held open until the audio clock and
  the wall clock meet.
"""
from __future__ import annotations

import asyncio
import time

import pytest


class _Session:
    def __init__(self) -> None:
        self.starts = 0
        self.ends = 0
        self.audio = 0

    async def send_realtime_input(self, **kwargs):
        if "activity_start" in kwargs:
            self.starts += 1
        elif "activity_end" in kwargs:
            self.ends += 1
        elif "audio" in kwargs:
            self.audio += 1


class _Reader:
    """Hands over every frame at once, the way a drained queue does.

    `pending()` is the real reader's queue depth, and it is what the bridge
    asks: the first attempt compared clocks instead, and a device streaming in
    real time keeps its head start forever — so "still catching up" was true for
    the whole call and no turn was ever closed at all.
    """

    def __init__(self, chunks, backlog: int = 0) -> None:
        self._chunks = list(chunks)
        self._left = len(self._chunks)
        self._backlog = backlog
        self.dropped = 0

    def pending(self) -> int:
        """What was waiting when the bridge started — the only thing asked."""
        return self._backlog

    async def frames(self):
        for c in self._chunks:
            self._left -= 1
            yield c


def _speech(ms: int, loud: bool = True) -> bytes:
    import numpy as np

    n = int(16000 * ms / 1000)
    level = 3000 if loud else 5
    return (np.full(n, level, dtype="<i2")).tobytes()


@pytest.fixture()
def loop():
    lp = asyncio.new_event_loop()
    try:
        yield lp
    finally:
        lp.run_until_complete(lp.shutdown_asyncgens())
        lp.close()


def test_a_drained_buffer_is_one_question(loop, monkeypatch):
    """Ten seconds of buffered speech arriving instantly must not become four
    turns. Each extra turn cancels the reply to the one before it."""
    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    # A sentence, a pause, more sentence — the shape of ordinary speech.
    chunks = ([_speech(400)] * 5 + [_speech(400, loud=False)] * 3
              + [_speech(400)] * 5 + [_speech(400, loud=False)] * 3
              + [_speech(400)] * 5)
    session = _Session()

    loop.run_until_complete(
        _device_to_live(_Reader(chunks, backlog=len(chunks)), session,
                        _RecentAudio(), verify=False))

    assert session.audio > 0, "no audio was forwarded at all"
    assert session.ends <= 1, (
        f"{session.ends} turns closed while draining a backlog — each one after "
        "the first cancels the reply to the previous")


def test_a_pause_in_real_time_still_ends_the_turn(loop):
    """The hold is for catching up, not a mute button. Once the audio clock and
    the wall clock meet, a pause means what it has always meant — otherwise the
    fix for "she answers nothing" is "she waits forever"."""
    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    class _LiveReader(_Reader):
        def pending(self) -> int:
            return 0        # a live mic keeps nothing waiting

        async def frames(self):
            for c in self._chunks:
                # Play it out at roughly its own duration, like a live mic.
                await asyncio.sleep(0.2)
                yield c

    chunks = [_speech(200)] * 3 + [_speech(200, loud=False)] * 5
    session = _Session()

    t0 = time.monotonic()
    loop.run_until_complete(
        _device_to_live(_LiveReader(chunks), session, _RecentAudio(), verify=False))
    assert time.monotonic() - t0 > 1.0, "the fixture did not run in real time"

    assert session.starts == 1
    assert session.ends == 1, "a real pause no longer ends the turn"


def test_the_instruction_is_cached_per_tenant_version(monkeypatch):
    """The seconds that create the backlog in the first place.

    Measured on the robot: persona 256ms, legacy memory 258ms, short-term
    history 1400ms, context 3860ms — six seconds before Gemini is even dialled,
    with the microphone running the whole time.
    """
    import app.api.voice_ws.tools as vt

    vt.clear_instruction_cache()
    calls = {"n": 0}

    monkeypatch.setattr(vt, "_system_instruction_body",
                        lambda cid, persona: (calls.__setitem__("n", calls["n"] + 1)
                                              or "التعليمات"))
    monkeypatch.setattr("app.utils.tenant_version.version_for", lambda t: 7)

    assert vt._cached_system_instruction("u1", None) == "التعليمات"
    assert vt._cached_system_instruction("u1", None) == "التعليمات"
    assert calls["n"] == 1, "every call rebuilds the whole instruction"

    # A write moves the version, and the next session must see it.
    monkeypatch.setattr("app.utils.tenant_version.version_for", lambda t: 8)
    vt._cached_system_instruction("u1", None)
    assert calls["n"] == 2, "a saved memory never reached the voice prompt"
    vt.clear_instruction_cache()


def test_two_tenants_do_not_share_an_instruction(monkeypatch):
    import app.api.voice_ws.tools as vt

    vt.clear_instruction_cache()
    monkeypatch.setattr("app.utils.tenant_version.version_for", lambda t: 1)
    monkeypatch.setattr(vt, "_system_instruction_body",
                        lambda cid, persona: f"تعليمات {cid}")

    assert vt._cached_system_instruction("u1", None) == "تعليمات u1"
    assert vt._cached_system_instruction("u2", None) == "تعليمات u2"
    vt.clear_instruction_cache()


def test_the_ingest_pool_does_not_hold_the_dyno_open():
    """`Error R12 (Exit timeout)` on the deploy that added it: the pool's worker
    is joined at interpreter exit and can be sitting on a Mongo call."""
    import atexit

    import app.integrations.mqtt_ingest as mi

    assert callable(mi._drop_pending_ingest)
    # Registered, and safe to call twice — atexit will call it once more.
    mi._drop_pending_ingest()
    atexit.unregister(mi._drop_pending_ingest)


def test_the_hold_lifts_and_stays_lifted(loop):
    """**A test that can stay true forever is not a test.**

    Asking "is the queue deep right now" on every frame never released: a device
    sending one frame every hundred and thirty milliseconds keeps one or two in
    flight permanently, so the hold survived the whole call —

        07:42:40  66 frames still queued — holding the turn open
        07:43:22  device→live done: 105 frames, 13.4s audio

    thirty-nine seconds of speech in the earlier one, and not a single
    `turn closed`. The backlog is a fact about the beginning of a call, so it is
    decided once.
    """
    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    class _NeverEmpties(_Reader):
        """A live device: always a frame or two in flight, forever. Under the
        old per-frame check this never released."""

        def pending(self) -> int:
            return 3

    chunks = ([_speech(300)] * 8 + [_speech(300, loud=False)] * 4
              + [_speech(300)] * 4 + [_speech(300, loud=False)] * 4)
    session = _Session()

    loop.run_until_complete(
        _device_to_live(_NeverEmpties(chunks), session, _RecentAudio(),
                        verify=False))

    assert session.ends >= 1, (
        "the hold never lifted — a device that always has a frame in flight "
        "would never get an answer at all")


def test_a_noisy_room_still_gets_an_answer(loop):
    """**The bug that produced a whole day of silence.**

    The threshold was a constant, 350, and the room's own floor was above it —
    so every frame counted as speech, the seven hundred milliseconds of quiet
    that end a turn never accumulated, and Gemini was never told the question
    was over. Not one `turn closed` line in thirty-nine seconds of talking.
    """
    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    def _at(level: int, ms: int = 300) -> bytes:
        import numpy as np
        return np.full(int(16000 * ms / 1000), level, dtype="<i2").tobytes()

    # A room humming well above the old constant, then a sentence, then the room
    # again. The pause is quiet *for this room*, which is the only sense in which
    # any pause is ever quiet.
    chunks = ([_at(600)] * 4 + [_at(6000)] * 6 + [_at(600)] * 6)
    session = _Session()

    loop.run_until_complete(
        _device_to_live(_Reader(chunks), session, _RecentAudio(), verify=False))

    assert session.starts >= 1, "the sentence was never heard over the room"
    assert session.ends >= 1, (
        "the turn never closed — Gemini was never told the question was over, "
        "which is exactly what silence sounds like from the other end")


def test_a_quiet_room_does_not_turn_a_hiss_into_a_sentence(loop):
    """The other way to be wrong. With no absolute minimum, a floor near zero
    makes any faint noise stand out by the required margin."""
    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    def _at(level: int, ms: int = 300) -> bytes:
        import numpy as np
        return np.full(int(16000 * ms / 1000), level, dtype="<i2").tobytes()

    chunks = [_at(3)] * 6 + [_at(20)] * 4 + [_at(3)] * 6
    session = _Session()

    loop.run_until_complete(
        _device_to_live(_Reader(chunks), session, _RecentAudio(), verify=False))

    assert session.starts == 0, "a hiss in a silent room opened a turn"
