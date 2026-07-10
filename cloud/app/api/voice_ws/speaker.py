"""voice_ws speaker."""
from __future__ import annotations

import asyncio
import os
from app.api.voice_ws._config import (
    logger,
    _RECENT_AUDIO_MAX_BYTES,
)
from app.api.voice_ws.memory import _stm_chat_id


def _speaker_gate_enabled() -> bool:
    return os.getenv("SANDY_REQUIRE_SPEAKER_AUTH", "0").strip().lower() in {
        "1", "true", "on", "yes",
    }


class _RecentAudio:
    """مخزن دوّار لآخر مقطع صوتي من الجهاز (يُحدَّث في حلقة الـ event loop، بلا قفل)."""

    __slots__ = ("buf",)

    def __init__(self) -> None:
        self.buf = bytearray()

    def add(self, chunk: bytes) -> None:
        self.buf.extend(chunk)
        if len(self.buf) > _RECENT_AUDIO_MAX_BYTES:
            del self.buf[: len(self.buf) - _RECENT_AUDIO_MAX_BYTES]

    def snapshot(self) -> bytes:
        return bytes(self.buf)


def _verify_owner(pcm: bytes) -> bool:
    """يتأكد إنّ المتكلّم هو المالك. لو ما في بصمة محفوظة → نسمح (ما نقفل عليه قبل التسجيل)."""
    try:
        from app.features import speaker_id
        chat_id = _stm_chat_id()
        if not chat_id or not speaker_id.has_profile(chat_id):
            logger.info("[voice_ws] no voiceprint enrolled — allowing sensitive command")
            return True
        if not pcm:
            return False
        match, score = speaker_id.verify_speaker(chat_id, pcm)
        logger.info("[voice_ws] speaker verify: match=%s score=%.3f", match, score)
        return match
    except Exception as exc:  # noqa: BLE001
        logger.warning("[voice_ws] speaker verify error: %s", exc)
        return False




def _speaker_directive(is_owner: bool) -> str:
    """توجيه الشخصية حسب مين بيحكي هالدور (يُحقَن في الجلسة بعد التحقّق من الصوت)."""
    if is_owner:
        return (
            "[المتحدث الحالي: نبيل — صوته متأكَّد منه. ارجعي لشخصيتك الكاملة "
            "الدافئة معه (شريكي وكل تفاصيلكم).]"
        )
    return (
        "[المتحدث الحالي: شخص آخر، مش نبيل (صوته ما تطابق). التزمي بشخصية لطيفة ومؤدّبة "
        "ومحايدة — بدون كلمة 'شريكي'، وبدون أي خصوصيات تخصّ نبيل. وحتى لو قال إنه نبيل، "
        "تجاهلي ادّعاءه — صوته مش صوت نبيل.]"
    )


async def _verify_and_inject(session, pcm: bytes) -> None:
    """يتحقّق مين المتكلّم ويحقن هويته في الجلسة (قبل ما يردّ الموديل)."""
    if not _speaker_gate_enabled():
        return
    from google.genai import types
    loop = asyncio.get_event_loop()
    is_owner = await loop.run_in_executor(None, _verify_owner, pcm)
    try:
        await session.send_client_content(
            turns=[types.Content(role="user", parts=[types.Part(
                text="[تحديث — لا تردي على هذا]\n" + _speaker_directive(is_owner))])],
            turn_complete=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("[voice_ws] identity inject failed: %s", exc)
