"""واحد وتلاتين ثانية مكالمة، والسجل بيقول «من الجهاز للبث: صفر إطار».

    [voice_ws] 68 frames were buffered during setup — one turn, not several
    [voice_ws] device→live done: 0 frames, 0 bytes, 0.0s audio, 0 frames dropped

السطرين مع بعض بيحصروا الخلل بمكان واحد: الصوت **وصل** للسيرفر (تمانية وستين
إطارًا كانوا بالطابور)، وما عدّى بوابة كشف الكلام ولا مرّة. يعني جيميناي ما سمع
ولا حرف، وهي ما ردّت — مش بطء، انقطاع.

والسبب إنّ أرضية الضجّة كانت محسوبة بـ**عدد إطارات**، مش بالوقت. اللوح إطاره
مية وتمانية وعشرين جزء من الألف، فأربعة وعشرين إطارًا = تلات ثواني، وبهالمدة
أكيد في وقفة بتكون هي الغرفة. التطبيق إطاره أربعين جزء تقريبًا، فنفس الرقم صار
**ثانية وحدة**، وثانية من نصّ جملة ما فيها ولا وقفة — فأهدأ لحظة فيها هي أهدأ
كلمة، والعتبة انبنت فوق صوته وضلّت فوقه.

وأسوأ لحظة لهالحساب هي أول المكالمة بالذات: اللي بالطابور وقت ما بلّشنا هو صوت
صاحبه وهو عم يحكي قبل ما تفتح الجلسة.
"""
from __future__ import annotations

import asyncio

import numpy as np
import pytest


def _tone(n: int, level: float):
    """`n` samples of a voice-like tone (160 Hz) whose loudness (RMS) is `level`:
    the server counts only pitched sound as someone talking over her."""

    t = np.arange(int(n)) / 16000
    return (level * np.sqrt(2) * np.sin(2 * np.pi * 160 * t)).astype("<i2")



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
    def __init__(self, chunks, backlog: int = 0) -> None:
        self._chunks = list(chunks)
        self._backlog = backlog
        self.dropped = 0

    def pending(self) -> int:
        return self._backlog

    async def frames(self):
        for c in self._chunks:
            yield c


def _app_frame(level: int, ms: int = 40) -> bytes:
    """إطار بطول اللي بيبعتو التطبيق — أربعين جزء من الألف، مش مية وتمانية وعشرين."""
    return _tone(int(16000 * ms / 1000), level).tobytes()


@pytest.fixture()
def loop():
    lp = asyncio.new_event_loop()
    try:
        yield lp
    finally:
        lp.run_until_complete(lp.shutdown_asyncgens())
        lp.close()


def test_a_buffer_that_starts_mid_sentence_still_opens_the_gate(loop):
    """صاحبه بلّش يحكي قبل ما تفتح الجلسة، فأول اللي بالطابور صوته هو.

    قبل التصليح: أول أربع إطارات كلام، فأهدأ إطار عندنا هو كلام، والعتبة بتصير
    ضعفينه ونص — وما بتفتح أبدًا. تلات ثواني كلام، صفر إطار طالع.
    """
    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    # ما في برولّ غرفة أبدًا: الطابور بيبلّش بصوته، وشدّته ثابتة تقريبًا زي ما
    # بتطلع من معالجة الصوت بالأيفون.
    chunks = [_app_frame(2000)] * 75          # تلات ثواني كلام متواصل
    session = _Session()

    loop.run_until_complete(
        _device_to_live(_Reader(chunks, backlog=len(chunks)), session,
                        _RecentAudio(), verify=False))

    assert session.starts == 1, "البوابة ما فتحت — نفس «صفر إطار» يلّي بالسجل"
    assert session.audio >= 60, (
        f"{session.audio} قطعة بس وصلت جيميناي من خمسة وسبعين إطار — "
        "أول السؤال ضايع")


def test_the_room_is_measured_in_seconds_not_in_frames(loop):
    """نفس المشهد بالضبط، بس بإطارات اللوح — لازم يطلع نفس السلوك.

    هاد هو الفرق يلّي كان: نفس الكود، جهازين، ونتيجتين. الاختبار بيمسك الرجعة
    لعدّ الإطارات لأنّ الأربعة وعشرين إطار بيصيروا معنى تاني بكل جهاز.
    """
    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    board = [_app_frame(2000, ms=128)] * 24   # نفس التلات ثواني، إطارات اللوح
    app = [_app_frame(2000, ms=40)] * 75

    out = []
    for chunks in (board, app):
        session = _Session()
        loop.run_until_complete(
            _device_to_live(_Reader(chunks, backlog=len(chunks)), session,
                            _RecentAudio(), verify=False))
        out.append(session.starts)

    assert out[0] == out[1] == 1, (
        f"اللوح فتح {out[0]} مرّة والتطبيق {out[1]} — نفس الصوت، نفس الثواني")


def test_a_turn_cannot_stay_open_for_ever(loop):
    """الشبكة من الجهة التانية: تقدير واطي كتير بيخلّي كل الغرفة كلام.

    ساعتها الصمت اللي بينهي الدور ما بيتجمّع أبدًا، والتطبيق ما بيوقف الإرسال
    فحتى الفجوة ما بتجي — والنتيجة نفسها: ما بتردّ. فالدور بينتهي بالسقف.
    """
    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    chunks = [_app_frame(2000)] * 600         # أربعة وعشرين ثانية بلا ولا وقفة
    session = _Session()

    loop.run_until_complete(
        _device_to_live(_Reader(chunks), session, _RecentAudio(), verify=False))

    assert session.ends >= 1, "الدور ضلّ مفتوح للأبد — جيميناي ما بيعرف إنّ السؤال خلص"


def test_the_floor_windows_are_times_not_counts():
    from app.api.voice_ws import _config as cfg

    assert cfg._VAD_FLOOR_MS >= 2000, "أقصر من هيك ما بيضمن وقفة جوا النافذة"
    assert cfg._VAD_ROOM_MS > cfg._VAD_FLOOR_MS, "نافذة الأمان لازم تكون أطول"
    assert not hasattr(cfg, "_VAD_FLOOR_FRAMES"), (
        "نافذة بعدد الإطارات بتعني مدّة مختلفة بكل جهاز — هاد الخلل نفسه")


class _StatefulSession(_Session):
    """بتسجّل ترتيب الأحداث، عشان نعرف وين وقع الدور مش بس كم مرّة."""

    def __init__(self) -> None:
        super().__init__()
        self.order: list[str] = []

    async def send_realtime_input(self, **kwargs):
        await super().send_realtime_input(**kwargs)
        if "activity_start" in kwargs:
            self.order.append("start")
        elif "activity_end" in kwargs:
            self.order.append("end")


def _pause(ms: int = 40) -> bytes:
    return _app_frame(5, ms=ms)


def test_a_pause_inside_a_sentence_does_not_end_it(loop):
    """«بدّي... (يفكّر)... تذكّريني بكرا» — الوقفة بالنصّ سكّرت الدور وردّت ع نصّ
    السؤال. الكلام اللي إجا بعد الإقفال وقبل ما تقول هي ولا كلمة هو تكملة."""
    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    chunks = ([_pause()] * 6 + [_app_frame(2000)] * 30      # نصّ الجملة الأوّل
              + [_pause()] * 30                              # وقفة تفكير أطول من الحدّ
              + [_app_frame(2000)] * 23                      # وكمّل — أقصر من حدّ المقاطعة
              + [_pause()] * 40)                             # وخلص فعلًا
    session = _StatefulSession()
    state: dict = {}

    loop.run_until_complete(
        _device_to_live(_Reader(chunks), session, _RecentAudio(),
                        verify=False, live_state=state))

    # الدور الأوّل بينسكّر (الوقفة طويلة فعلًا)، بس التكملة لازم تفتح دورًا
    # وتوصل — مش تنحجز كأنها مقاطعة لردّ ما بلّش.
    assert session.order.count("start") == 2, (
        f"التكملة ما فتحت دور: {session.order}")
    assert session.order[-1] == "end", "آخر إشي لازم يكون إقفال، وإلا ما بتردّ"


def test_the_bar_goes_back_up_once_she_starts_talking(loop):
    """الفرق كلّو بالكلفة: إلغاء ردّ ما بلّش غير إلغاء ردّ نصّو طالع."""
    import time as _time

    from app.api.voice_ws import _config as cfg
    from app.api.voice_ws.session import _barge_bar_ms

    now = _time.monotonic()
    assert _barge_bar_ms({"turn_closed_at": now}) == cfg._CONTINUE_MIN_MS
    # قالت كلمة بعد الإقفال ← صار في ردّ يتقاطع، والحدّ بيرجع كامل.
    assert _barge_bar_ms(
        {"turn_closed_at": now, "last_out_at": now + 0.2}) == cfg._BARGE_MIN_MS
    assert cfg._CONTINUE_MIN_MS < cfg._BARGE_MIN_MS


def test_the_app_hands_every_frame_to_gemini_and_never_ends_a_turn_itself(loop):
    """مكالمة التطبيق: جيميناي بيقرّر وين الدور — زي تطبيق جيميناي نفسه.

    من عنّا ولا بداية دور ولا نهايته: لو بعتنا وحدة، رجعنا نقطع الجملة ع وقفة
    التفكير، وهاد بالضبط اللي خلّانا ننقل القرار.
    """
    from app.api.voice_ws.session import _device_to_live_auto
    from app.api.voice_ws.speaker import _RecentAudio

    chunks = ([_pause()] * 10 + [_app_frame(2000)] * 20 + [_pause()] * 30
              + [_app_frame(2000)] * 20 + [_pause()] * 10)
    session = _StatefulSession()
    state: dict = {}

    loop.run_until_complete(
        _device_to_live_auto(_Reader(chunks), session, _RecentAudio(),
                             live_state=state))

    assert session.order == [], f"قرّرنا الدور بدل جيميناي: {session.order}"
    assert session.audio == len(chunks), "في صوت ما وصل — حتى الصمت لازم يوصل"
    assert "turn_closed_at" in state, "ما في «آخر ما سمعناك» لقياس أول ردّ"


def test_a_question_whose_transcript_has_no_words_is_not_saved_as_dots():
    from app.api.voice_ws.session import _HAS_LETTERS

    assert _HAS_LETTERS.search(". . . .") is None
    assert _HAS_LETTERS.search("اعرف عن المصطلحات") is not None
    assert _HAS_LETTERS.search("what is it") is not None


def test_talking_over_her_from_the_app_interrupts_her(loop):
    """المايك صار مفتوح وهي بتحكي — والمقاطعة بتمرق بحدّها الكامل.

    إطارات التطبيق مع إلغاء الصدى بتوصل مية جزء من الألف. قبل ما يصير سقف
    الحجز بالوقت، ستّاشر إطار ما كانوا يكفوا يعدّوا الحدّ بأي طول حكي.
    """
    import time as _time

    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    chunks = [_app_frame(30, ms=100)] * 10 + [_app_frame(3000, ms=100)] * 16
    session = _StatefulSession()
    # عم تحكي هلّق: آخر صوت منها طلع هلّق، والدور تبعو انسكّر من قبل.
    now = _time.monotonic()
    state: dict = {"replying": True, "turn_closed_at": now - 3, "last_out_at": now + 60}

    loop.run_until_complete(
        _device_to_live(_Reader(chunks), session, _RecentAudio(),
                        verify=False, live_state=state))

    assert session.order[:1] == ["start"], (
        f"حكى ثانية ونص فوقها وما انقطعت: {session.order}")
    assert state["replying"] is False, "بعد المقاطعة لسا معتبرينها عم تردّ"


def test_street_noise_over_her_does_not_cut_her_off(loop):
    """A car outside for three seconds is loud, but not a voice: her answer goes on."""
    import time as _time


    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    noise = np.random.default_rng(3).normal(0, 3000, 1600).astype("<i2").tobytes()
    chunks = [_app_frame(30, ms=100)] * 10 + [noise] * 30
    session = _StatefulSession()
    now = _time.monotonic()
    state: dict = {"replying": True, "turn_closed_at": now - 3, "last_out_at": now + 60}

    loop.run_until_complete(
        _device_to_live(_Reader(chunks), session, _RecentAudio(),
                        verify=False, live_state=state))

    assert "start" not in session.order, f"noise cut her off: {session.order}"


def test_a_bang_while_she_is_quiet_does_not_open_a_turn(loop):
    """A door or the TV while she is idle used to open a turn: Gemini answered the noise
    («sorry about that…»). Only a voice opens one now, and its first words still reach her."""
    from app.api.voice_ws.session import _device_to_live
    from app.api.voice_ws.speaker import _RecentAudio

    noise = np.random.default_rng(5).normal(0, 3000, 1600).astype("<i2").tobytes()
    room = [_app_frame(30, ms=100)] * 10
    session = _StatefulSession()
    loop.run_until_complete(
        _device_to_live(_Reader(room + [noise] * 20), session, _RecentAudio(),
                        verify=False, live_state={}))
    assert "start" not in session.order, f"noise opened a turn: {session.order}"

    session = _StatefulSession()
    loop.run_until_complete(
        _device_to_live(_Reader(room + [_app_frame(3000, ms=100)] * 10), session, _RecentAudio(),
                        verify=False, live_state={}))
    assert "start" in session.order


def test_a_frame_cut_mid_sample_does_not_end_the_call(loop):
    """Live log: «buffer size must be a multiple of element size» and the call dropped. A
    message can end mid-sample; the stray byte now waits for the next one."""
    from app.api.voice_ws.session import _DeviceReader

    reader = _DeviceReader(ws=None)
    for part in (b"\x01\x00\x02", b"\x00\x03\x00", b"\x04", None):
        reader._q.put_nowait(part)

    async def take():
        return [c async for c in reader.frames()]

    frames = loop.run_until_complete(take())
    assert all(len(f) % 2 == 0 for f in frames)
    assert b"".join(frames) == b"\x01\x00\x02\x00\x03\x00"
    reader._pool.shutdown(wait=False)
