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
    return np.full(int(16000 * ms / 1000), level, dtype="<i2").tobytes()


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
